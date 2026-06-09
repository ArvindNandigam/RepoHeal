import gc
import uuid
import traceback
import shutil
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

from app.config import settings
from app.db.database import get_mongo_db
from app.utils.logger import get_logger

logger = get_logger(__name__)


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    ANALYZING = "analyzing"
    GENERATING_GRAPH = "generating_graph"
    GENERATING_REPORTS = "generating_reports"
    GENERATING_MIGRATIONS = "generating_migrations"
    UPDATING_METADATA = "updating_metadata"
    COMPLETED = "completed"
    FAILED = "failed"
    OUTDATED = "outdated"
    UP_TO_DATE = "up_to_date"
    ORPHANED = "orphaned"
    CANCELLED = "cancelled"


ACTIVE_STATUSES = {
    JobStatus.QUEUED.value,
    JobStatus.RUNNING.value,
    JobStatus.ANALYZING.value,
    JobStatus.GENERATING_GRAPH.value,
    JobStatus.GENERATING_REPORTS.value,
    JobStatus.GENERATING_MIGRATIONS.value,
    JobStatus.UPDATING_METADATA.value,
}

# New: statuses that indicate a job was actively running when process died
RUNNING_STATUSES = {
    JobStatus.RUNNING.value,
    JobStatus.ANALYZING.value,
    JobStatus.GENERATING_GRAPH.value,
    JobStatus.GENERATING_REPORTS.value,
    JobStatus.GENERATING_MIGRATIONS.value,
    JobStatus.UPDATING_METADATA.value,
}

MAX_CACHE_SIZE_MB = getattr(settings, "MAX_CACHE_SIZE_MB", 500)
MAX_ANALYSIS_HISTORY = getattr(settings, "MAX_ANALYSIS_HISTORY", 5)
CACHE_RETENTION_DAYS = getattr(settings, "CACHE_RETENTION_DAYS", 30)
JOB_ORPHAN_TIMEOUT = getattr(settings, "JOB_ORPHAN_TIMEOUT_MINUTES", 15)


def recover_orphaned_jobs() -> int:
    """
    On startup, find jobs that were in a RUNNING_STATUSES but haven't been
    updated in JOB_ORPHAN_TIMEOUT minutes. Mark them as ORPHANED.
    Running jobs within the timeout window are left alone (they may still be alive).
    """
    db = get_mongo_db()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=JOB_ORPHAN_TIMEOUT)
    orphaned = db.jobs.update_many(
        {
            "status": {"$in": list(RUNNING_STATUSES)},
            "updated_at": {"$lt": cutoff},
        },
        {
            "$set": {
                "status": JobStatus.ORPHANED.value,
                "message": "Orphaned — process restarted during execution",
                "error": "Process restarted while job was running",
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )
    count = getattr(orphaned, "modified_count", 0)
    if count:
        logger.warning(f"Recovered {count} orphaned job(s) on startup")

    # Also mark stale QUEUED jobs as orphaned (they were queued before restart)
    stale_cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    stale_queued = db.jobs.update_many(
        {
            "status": JobStatus.QUEUED.value,
            "updated_at": {"$lt": stale_cutoff},
        },
        {
            "$set": {
                "status": JobStatus.ORPHANED.value,
                "message": "Orphaned — queued before process restart",
                "error": "Process restarted while job was queued",
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )
    count += getattr(stale_queued, "modified_count", 0)
    return count


def create_job(
    repo_owner: str,
    repo_name: str,
    skip_if_recent: bool = False,
    recent_hours: int = 24,
    force: bool = False,
    job_type: str = "analysis",
    target_mode: str = "latest",
    target_branch: str | None = None,
    target_commit_sha: str | None = None,
) -> str | None:
    """Register a new job in MongoDB and return its ID."""
    db = get_mongo_db()
    current = db.repository_analysis_status.find_one({
        "repo_owner": repo_owner,
        "repo_name": repo_name,
    })
    if current and current.get("status") in ACTIVE_STATUSES:
        return None

    completed_at = current.get("completed_at") if current else None
    if isinstance(completed_at, datetime) and completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=timezone.utc)
    if (
        not force
        and job_type == "analysis"
        and skip_if_recent
        and isinstance(completed_at, datetime)
        and completed_at >= datetime.now(timezone.utc) - timedelta(hours=recent_hours)
    ):
        return None

    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    db.jobs.insert_one({
        "job_id": job_id,
        "repo_owner": repo_owner,
        "repo_name": repo_name,
        "job_type": job_type,
        "target_mode": target_mode,
        "selected_branch": target_branch,
        "target_commit_sha": target_commit_sha,
        "status": JobStatus.QUEUED.value,
        "progress": 0,
        "current_step": "queued",
        "message": _queued_message(job_type),
        "result": None,
        "error": None,
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "completed_at": None,
        "expires_at": now + timedelta(hours=24),
    })
    update_repository_status(
        repo_owner,
        repo_name,
        JobStatus.QUEUED,
        0,
        _queued_message(job_type),
        job_id=job_id,
        job_type=job_type,
        selected_branch=target_branch,
        target_commit_sha=target_commit_sha,
    )
    return job_id


def _queued_message(job_type: str) -> str:
    return "Queued"


def update_job(
    job_id: str,
    status: JobStatus,
    result=None,
    error=None,
    progress: int | None = None,
    message: str | None = None,
    analysis_id: str | None = None,
    repository_snapshot_id: str | None = None,
    current_step: str | None = None,
):
    """Update job status in MongoDB."""
    db = get_mongo_db()
    update = {
        "status": status.value,
        "updated_at": datetime.now(timezone.utc),
    }
    if result is not None:
        update["result"] = result
    if error is not None:
        update["error"] = error
    if progress is not None:
        update["progress"] = progress
    if message is not None:
        update["message"] = message
    if analysis_id is not None:
        update["analysis_id"] = analysis_id
    if repository_snapshot_id is not None:
        update["repository_snapshot_id"] = repository_snapshot_id
    if current_step is not None:
        update["current_step"] = current_step
    if status == JobStatus.RUNNING:
        update["started_at"] = datetime.now(timezone.utc)
    if status == JobStatus.COMPLETED or status == JobStatus.FAILED or status == JobStatus.CANCELLED:
        update["completed_at"] = datetime.now(timezone.utc)

    db.jobs.update_one({"job_id": job_id}, {"$set": update})


def update_repository_status(
    repo_owner: str,
    repo_name: str,
    status: JobStatus,
    progress: int,
    message: str,
    job_id: str | None = None,
    error: str | None = None,
    job_type: str | None = None,
    selected_branch: str | None = None,
    target_commit_sha: str | None = None,
    current_head: str | None = None,
    analysis_id: str | None = None,
    repository_snapshot_id: str | None = None,
):
    """Persist the latest repository-level analysis state."""
    db = get_mongo_db()
    now = datetime.now(timezone.utc)
    update = {
        "repository": f"{repo_owner}/{repo_name}",
        "repo_owner": repo_owner,
        "repo_name": repo_name,
        "status": status.value,
        "progress": progress,
        "message": message,
        "updated_at": now,
    }
    if job_type:
        update["job_type"] = job_type
    if job_id:
        update["job_id"] = job_id
    if selected_branch:
        update["selected_branch"] = selected_branch
    if target_commit_sha:
        update["target_commit_sha"] = target_commit_sha
    if current_head:
        update["current_head"] = current_head
    if analysis_id:
        update["analysis_id"] = analysis_id
    if repository_snapshot_id:
        update["repository_snapshot_id"] = repository_snapshot_id
    if error is not None:
        update["error"] = error
    if status == JobStatus.COMPLETED or status == JobStatus.FAILED:
        update["completed_at"] = now
    if status == JobStatus.COMPLETED:
        if job_type == "health_refresh":
            update["last_health_refresh"] = now
        else:
            update["last_analysis"] = now
            if target_commit_sha:
                update["last_commit_analyzed"] = target_commit_sha

    operation = {
        "$set": update,
        "$setOnInsert": {"created_at": now},
    }
    if error is None:
        operation["$unset"] = {"error": ""}

    db.repository_analysis_status.update_one(
        {"repo_owner": repo_owner, "repo_name": repo_name},
        operation,
        upsert=True,
    )


def set_analysis_progress(
    job_id: str,
    repo_owner: str,
    repo_name: str,
    status: JobStatus,
    progress: int,
    message: str,
    error: str | None = None,
    job_type: str | None = None,
    selected_branch: str | None = None,
    target_commit_sha: str | None = None,
    current_head: str | None = None,
    analysis_id: str | None = None,
    repository_snapshot_id: str | None = None,
    current_step: str | None = None,
):
    update_job(
        job_id,
        status,
        error=error,
        progress=progress,
        message=message,
        analysis_id=analysis_id,
        repository_snapshot_id=repository_snapshot_id,
        current_step=current_step,
    )
    update_repository_status(
        repo_owner,
        repo_name,
        status,
        progress,
        message,
        job_id=job_id,
        error=error,
        job_type=job_type,
        selected_branch=selected_branch,
        target_commit_sha=target_commit_sha,
        current_head=current_head,
        analysis_id=analysis_id,
        repository_snapshot_id=repository_snapshot_id,
    )


def cancel_repository_jobs(repo_owner: str, repo_name: str, reason: str = "Repository uninstalled") -> int:
    """Mark active jobs as cancelled."""
    db = get_mongo_db()
    result = db.jobs.update_many(
        {
            "repo_owner": repo_owner,
            "repo_name": repo_name,
            "status": {"$in": list(ACTIVE_STATUSES)},
        },
        {
            "$set": {
                "status": JobStatus.CANCELLED.value,
                "progress": 0,
                "message": reason,
                "error": reason,
                "updated_at": datetime.now(timezone.utc),
                "completed_at": datetime.now(timezone.utc),
            }
        },
    )
    update_repository_status(repo_owner, repo_name, JobStatus.CANCELLED, 0, reason, error=reason)
    return getattr(result, "modified_count", 0)


def get_repository_status(repo_owner: str, repo_name: str):
    """Return persistent progress, including a not-started default."""
    db = get_mongo_db()
    doc = db.repository_analysis_status.find_one(
        {"repo_owner": repo_owner, "repo_name": repo_name},
        {"_id": 0},
    )
    if not doc:
        return {
            "repository": f"{repo_owner}/{repo_name}",
            "status": JobStatus.QUEUED.value,
            "progress": 0,
            "message": "Analysis has not started",
        }
    for field in ("created_at", "updated_at", "completed_at", "last_analysis", "last_health_refresh"):
        if isinstance(doc.get(field), datetime):
            doc[field] = doc[field].isoformat()
    current_head = doc.get("current_head")
    last_commit = doc.get("last_commit_analyzed") or doc.get("target_commit_sha")
    if current_head and last_commit:
        doc["code_state_status"] = "up_to_date" if current_head == last_commit else "outdated"
    return doc


def resolve_repository_target(repo, target_branch: str | None, target_commit_sha: str | None) -> dict:
    """Resolve a user-selected branch/commit to a GitHub archive ref and commit."""
    selected_branch = target_branch or getattr(repo, "default_branch", None) or "main"
    current_head = None
    try:
        current_head = repo.get_branch(selected_branch).commit.sha
    except Exception as exc:
        logger.warning(f"Could not resolve HEAD for {repo.full_name}:{selected_branch}: {exc}")

    commit_sha = target_commit_sha or current_head
    archive_ref = target_commit_sha or selected_branch
    return {
        "selected_branch": selected_branch,
        "commit_sha": commit_sha,
        "current_head": current_head,
        "archive_ref": archive_ref,
    }


def get_job(job_id: str):
    """Fetch a job by ID."""
    db = get_mongo_db()
    doc = db.jobs.find_one({"job_id": job_id}, {"_id": 0})
    if not doc:
        return None
    for field in ("created_at", "updated_at", "expires_at", "started_at", "completed_at"):
        if isinstance(doc.get(field), datetime):
            doc[field] = doc[field].isoformat()
    return doc


def get_active_jobs() -> list:
    """Return all jobs in an active/running status."""
    db = get_mongo_db()
    docs = list(
        db.jobs.find(
            {"status": {"$in": list(ACTIVE_STATUSES)}},
            {"_id": 0},
        ).sort("created_at", -1)
    )
    for doc in docs:
        for field in ("created_at", "updated_at", "expires_at", "started_at", "completed_at"):
            if isinstance(doc.get(field), datetime):
                doc[field] = doc[field].isoformat()
    return docs


def _clear_local_repository_cache(repo_owner: str, repo_name: str) -> None:
    from app.routers.dependencies import get_repo_cache_path

    cache_path = Path(get_repo_cache_path(repo_owner, repo_name))
    if cache_path.exists():
        shutil.rmtree(cache_path)
        logger.info(f"Cleared local RepoHeal cache at {cache_path}")


def _enforce_cache_governance() -> None:
    """
    Enforce cache size limits:
    1. Prune snapshots older than CACHE_RETENTION_DAYS
    2. Keep at most MAX_ANALYSIS_HISTORY analyses per repo
    3. If total cache exceeds MAX_CACHE_SIZE_MB, evict oldest repos
    """
    from app.routers.dependencies import REPO_CACHE_ROOT

    cache_root = Path(REPO_CACHE_ROOT)
    if not cache_root.exists():
        return

    now = datetime.now(timezone.utc)
    retention_limit = now - timedelta(days=CACHE_RETENTION_DAYS)

    for owner_dir in cache_root.iterdir():
        if not owner_dir.is_dir():
            continue
        for repo_dir in owner_dir.iterdir():
            meta_dir = repo_dir / ".repoheal"
            if not meta_dir.exists():
                continue

            # Prune old snapshots by mtime
            snap_dir = meta_dir / "snapshots"
            if snap_dir.exists():
                for snap_file in sorted(snap_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                    if snap_file.stat().st_mtime < retention_limit.timestamp():
                        snap_file.unlink()
                        logger.debug(f"Pruned old snapshot: {snap_file}")

            # Keep only MAX_ANALYSIS_HISTORY snapshots
            snapshot_files = sorted(snap_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            for old_snap in snapshot_files[MAX_ANALYSIS_HISTORY:]:
                old_snap.unlink()
                logger.debug(f"Pruned excess snapshot: {old_snap}")

    # Evict entire repos if total cache exceeds limit
    total_mb = 0
    repo_dirs = []
    for owner_dir in cache_root.iterdir():
        if not owner_dir.is_dir():
            continue
        for repo_dir in owner_dir.iterdir():
            size_mb = sum(f.stat().st_size for f in repo_dir.rglob("*") if f.is_file()) / 1024 / 1024
            last_access = max(f.stat().st_mtime for f in repo_dir.rglob("*") if f.is_file()) if any(True for _ in repo_dir.rglob("*")) else 0
            repo_dirs.append((repo_dir, size_mb, last_access))
            total_mb += size_mb

    if total_mb > MAX_CACHE_SIZE_MB:
        # Evict oldest-accessed repos first
        repo_dirs.sort(key=lambda x: x[2])
        for repo_dir, size_mb, _ in repo_dirs:
            if total_mb <= MAX_CACHE_SIZE_MB:
                break
            shutil.rmtree(repo_dir)
            total_mb -= size_mb
            logger.info(f"Evicted cache for {repo_dir} (cache over limit)")


def run_analysis_in_background(
    job_id: str,
    repo_owner: str,
    repo_name: str,
    force_reanalysis: bool = False,
    target_branch: str | None = None,
    target_commit_sha: str | None = None,
):
    """
    Synchronous function that runs the full analysis pipeline.
    Called from FastAPI BackgroundTasks.
    All progress is persisted to MongoDB — survives browser/tab close, logout, refresh.
    """
    from app.analysis.repository_analyzer import analyze_repository
    from app.github.repository_fetcher import download_repository_snapshot, cleanup_repository
    from app.storage.metadata_store import save_analysis_to_metadata
    from app.routers.dependencies import get_repo_cache_path
    from app.graph.graph_builder import Neo4jGraphBuilder

    from app.github.installations import get_repository_installation
    from app.github.client import RepoHealGitHubClient
    from app.intelligence.providers import create_intelligence_provider
    from app.intelligence.pipeline import MigrationPipeline
    from app.worker.metrics import (
        count_repository, count_analysis, count_commit, count_branch,
        record_code_scale, record_graph_scale, record_dependency_intelligence,
        record_impact_analysis, record_migration_metrics, record_analysis_duration,
    )
    from datetime import datetime as dt_mod, timezone as tz_mod
    import asyncio

    repo_id = f"{repo_owner}/{repo_name}"
    repo_path = None
    job_type = "reanalyze" if force_reanalysis else "analysis"
    selected_branch = target_branch
    commit_sha = target_commit_sha
    current_head = None
    _start = dt_mod.now(tz_mod.utc)
    analysis = None

    try:
        # Mark job as running
        set_analysis_progress(
            job_id, repo_owner, repo_name, JobStatus.RUNNING, 5,
            "Starting analysis", job_type=job_type, current_step="starting",
        )

        if force_reanalysis:
            _clear_local_repository_cache(repo_owner, repo_name)

        installation = get_repository_installation(repo_owner, repo_name)
        if not installation or "id" not in installation:
            raise PermissionError(f"RepoHeal is not installed on {repo_id}")

        github_client = RepoHealGitHubClient(installation["id"])
        repo_obj = github_client.get_repo(repo_id)
        target = resolve_repository_target(repo_obj, target_branch, target_commit_sha)
        selected_branch = target["selected_branch"]
        commit_sha = target["commit_sha"]
        current_head = target["current_head"]

        # --- Phase: Download ---
        set_analysis_progress(
            job_id, repo_owner, repo_name, JobStatus.ANALYZING, 10,
            "Downloading repository snapshot", job_type=job_type,
            selected_branch=selected_branch, target_commit_sha=commit_sha, current_head=current_head,
            current_step="download",
        )
        logger.info(f"Background analysis started for {repo_id} (job={job_id})")

        repo_path = download_repository_snapshot(repo_owner, repo_name, ref=target["archive_ref"])

        # --- Phase: Analyze ---
        set_analysis_progress(
            job_id, repo_owner, repo_name, JobStatus.ANALYZING, 30,
            "Extracting imports and dependencies", job_type=job_type,
            selected_branch=selected_branch, target_commit_sha=commit_sha, current_head=current_head,
            current_step="extracting",
        )
        set_analysis_progress(
            job_id, repo_owner, repo_name, JobStatus.ANALYZING, 50,
            "Analyzing repository structure", job_type=job_type,
            selected_branch=selected_branch, target_commit_sha=commit_sha, current_head=current_head,
            current_step="analyzing",
        )

        analysis = analyze_repository(repo_path)
        analysis["branch"] = selected_branch
        analysis["commit_sha"] = commit_sha
        save_analysis_to_metadata(str(get_repo_cache_path(repo_owner, repo_name)), analysis)

        # Record Tier 1 metrics
        count_repository(repo_id)
        count_analysis(repo_id)
        count_commit()
        if selected_branch:
            count_branch(selected_branch)

        summary = analysis.get("semantic_graph", {}).get("summary", {})
        imp_summary = analysis.get("imports", {}).get("summary", {})
        dep_graph = analysis.get("dependency_graph", {})

        py_files = imp_summary.get("total_python_files", 0)
        nb_files = imp_summary.get("total_notebooks", 0)
        funcs = summary.get("total_functions", 0)
        classes = summary.get("total_classes", 0)
        apis = summary.get("total_api_calls", 0)
        record_code_scale(py_files, nb_files, funcs, classes, apis, 0)

        deps_count = len(dep_graph)
        unique_pkgs = len(set(p.lower() for p in dep_graph.keys()))
        record_dependency_intelligence(deps_count, unique_pkgs, 0, 0, 0)

        # Free scan intermediate data
        del dep_graph, summary, imp_summary
        gc.collect()

        # --- Phase: Graph Build ---
        set_analysis_progress(
            job_id, repo_owner, repo_name, JobStatus.GENERATING_GRAPH, 75,
            "Building Neo4j knowledge graph", job_type=job_type,
            selected_branch=selected_branch, target_commit_sha=commit_sha, current_head=current_head,
            current_step="graph",
        )
        graph_builder = Neo4jGraphBuilder()
        graph_builder.clear_repository_graph(repo_id)
        graph_builder.build_graph(repo_id, analysis)

        node_count = (
            len(analysis.get("semantic_graph", {}).get("files", {}))
            + len(analysis.get("dependency_graph", {}))
        )
        edge_count = sum(
            len(f.get("calls", [])) + len(f.get("apis", []))
            for f in (analysis.get("semantic_graph", {}).get("files", {}) or {}).values()
        )
        record_graph_scale(repo_id, max(node_count, 1), max(edge_count, 1))

        del graph_builder, node_count, edge_count
        gc.collect()

        # --- Phase: Metadata persistence ---
        set_analysis_progress(
            job_id, repo_owner, repo_name, JobStatus.UPDATING_METADATA, 90,
            "Writing analysis metadata to repoheal.meta", job_type=job_type,
            selected_branch=selected_branch, target_commit_sha=commit_sha, current_head=current_head,
            current_step="metadata",
        )

        from app.github.metadata_branch import MetadataBranchManager

        metadata_manager = MetadataBranchManager(github_client)
        analysis_id, snapshot_id, _ = metadata_manager.generate_ids(repo_id, selected_branch, commit_sha)
        analysis["analysis_id"] = analysis_id
        analysis["repository_snapshot_id"] = snapshot_id

        # Save analysis metadata only — Cytoscape graph is generated on-demand
        # (Phase 5 optimization: lazy graph)
        metadata_manager.save_latest_analysis(
            repo_obj, repo_id, analysis, None,
            source_branch=selected_branch, commit_sha=commit_sha,
        )

        # --- Phase: Migration pipeline ---
        set_analysis_progress(
            job_id, repo_owner, repo_name, JobStatus.GENERATING_MIGRATIONS, 95,
            "Correlating intelligence and generating migration documents",
            job_type=job_type, selected_branch=selected_branch,
            target_commit_sha=commit_sha, current_head=current_head,
            analysis_id=analysis_id, repository_snapshot_id=snapshot_id,
            current_step="migrations",
        )
        try:
            async def run_pipeline():
                intelligence_provider = create_intelligence_provider()
                pipeline = MigrationPipeline(intelligence_provider, github_client)
                try:
                    report = await pipeline.run(
                        analysis, repo_id, repo_obj,
                        analysis_id=analysis_id,
                        source_branch=selected_branch,
                        commit_sha=commit_sha,
                    )
                    logger.info(f"Migration pipeline finished for {repo_id} with score {report.overall_health_score}")
                finally:
                    await intelligence_provider.close()

            asyncio.run(run_pipeline())
        except Exception as pipeline_err:
            logger.error(f"Migration pipeline failed for {repo_id}: {pipeline_err}")

        # Free analysis after pipeline
        del analysis
        gc.collect()

        # --- Completion ---
        update_job(
            job_id, JobStatus.COMPLETED,
            result={
                "repository": repo_id,
                "status": "analyzed",
                "analysis_id": analysis_id,
                "repository_snapshot_id": snapshot_id,
            },
            progress=100, message="Completed",
            analysis_id=analysis_id, repository_snapshot_id=snapshot_id,
            current_step="completed",
        )
        update_repository_status(
            repo_owner, repo_name, JobStatus.COMPLETED, 100, "Completed",
            job_id=job_id, job_type=job_type,
            selected_branch=selected_branch, target_commit_sha=commit_sha,
            current_head=current_head, analysis_id=analysis_id,
            repository_snapshot_id=snapshot_id,
        )
        logger.info(f"Background analysis completed for {repo_id} (job={job_id})")

        _elapsed = (dt_mod.now(tz_mod.utc) - _start).total_seconds()
        record_analysis_duration(_elapsed, success=True)

        # Phase 6: Record health snapshot
        try:
            from app.worker.monitoring_worker import record_health_snapshot, generate_alerts_from_report
            meta_manager = MetadataBranchManager(github_client)
            report_data = meta_manager.load_latest_report(repo_obj)
            if report_data and report_data.get("report"):
                report = report_data["report"]
                db_mongo = get_mongo_db()
                prev = db_mongo.health_scores.find_one(
                    {"repository": repo_id}, sort=[("recorded_at", -1)]
                )
                prev_score = prev.get("health_score") if prev else None
                record_health_snapshot(repo_id, analysis_id, report)
                alert_count = generate_alerts_from_report(repo_id, report, prev_score)
                if alert_count:
                    logger.info(f"Generated {alert_count} alerts for {repo_id}")
        except Exception as monitor_err:
            logger.warning(f"Monitoring update failed for {repo_id}: {monitor_err}")

        # Enforce cache governance after each analysis
        try:
            _enforce_cache_governance()
        except Exception as cache_err:
            logger.warning(f"Cache governance failed: {cache_err}")

    except Exception as e:
        _elapsed = (dt_mod.now(tz_mod.utc) - _start).total_seconds()
        record_analysis_duration(_elapsed, success=False)
        error_msg = traceback.format_exc()
        set_analysis_progress(
            job_id, repo_owner, repo_name, JobStatus.FAILED, 0,
            "Analysis failed", error=str(e), job_type=job_type,
            selected_branch=selected_branch, target_commit_sha=commit_sha,
            current_head=current_head, current_step="failed",
        )
        logger.error(f"Background analysis failed for {repo_id} (job={job_id}): {error_msg}")

    finally:
        if repo_path:
            cleanup_repository(repo_path)


def run_health_refresh_in_background(
    job_id: str,
    repo_owner: str,
    repo_name: str,
    target_branch: str | None = None,
    target_commit_sha: str | None = None,
):
    """Refresh migration intelligence using the latest stored analysis snapshot."""
    from app.routers.dependencies import load_cached_analysis
    from app.github.installations import get_repository_installation
    from app.github.client import RepoHealGitHubClient
    from app.intelligence.providers import create_intelligence_provider
    from app.intelligence.pipeline import MigrationPipeline
    import asyncio

    repo_id = f"{repo_owner}/{repo_name}"
    job_type = "health_refresh"
    selected_branch = target_branch
    commit_sha = target_commit_sha
    current_head = None

    try:
        set_analysis_progress(
            job_id, repo_owner, repo_name, JobStatus.RUNNING, 5,
            "Starting health refresh", job_type=job_type, current_step="starting",
        )

        installation = get_repository_installation(repo_owner, repo_name)
        if not installation or "id" not in installation:
            raise PermissionError(f"RepoHeal is not installed on {repo_id}")

        github_client = RepoHealGitHubClient(installation["id"])
        repo_obj = github_client.get_repo(repo_id)
        target = resolve_repository_target(repo_obj, target_branch, target_commit_sha)
        selected_branch = target["selected_branch"]
        commit_sha = target["commit_sha"]
        current_head = target["current_head"]

        set_analysis_progress(
            job_id, repo_owner, repo_name, JobStatus.GENERATING_REPORTS, 50,
            "Generating health reports and migration documents",
            job_type=job_type, selected_branch=selected_branch,
            target_commit_sha=commit_sha, current_head=current_head,
            current_step="reports",
        )

        from app.github.metadata_branch import MetadataBranchManager
        metadata_manager = MetadataBranchManager(github_client)
        record = None
        if commit_sha:
            record = metadata_manager.load_analysis_record(repo_obj, selected_branch, commit_sha)
        analysis = (record or {}).get("analysis") or load_cached_analysis(repo_owner, repo_name)
        if not analysis or not analysis.get("dependency_graph"):
            raise ValueError("No analysis snapshot found for health refresh")
        analysis["branch"] = selected_branch
        analysis["commit_sha"] = commit_sha

        async def run_pipeline():
            intelligence_provider = create_intelligence_provider()
            pipeline = MigrationPipeline(intelligence_provider, github_client)
            try:
                return await pipeline.run(
                    analysis, repo_id, repo_obj,
                    source_branch=selected_branch, commit_sha=commit_sha,
                )
            finally:
                await intelligence_provider.close()

        report = asyncio.run(run_pipeline())

        del analysis
        gc.collect()

        update_job(
            job_id, JobStatus.COMPLETED,
            result={
                "repository": repo_id,
                "status": "health_refreshed",
                "overall_health_score": report.overall_health_score,
            },
            progress=100, message="Completed",
            current_step="completed",
        )
        update_repository_status(
            repo_owner, repo_name, JobStatus.COMPLETED, 100, "Completed",
            job_id=job_id, job_type=job_type,
            selected_branch=selected_branch, target_commit_sha=commit_sha,
            current_head=current_head,
        )
    except Exception as e:
        error_msg = traceback.format_exc()
        set_analysis_progress(
            job_id, repo_owner, repo_name, JobStatus.FAILED, 0,
            "Health refresh failed", error=str(e), job_type=job_type,
            selected_branch=selected_branch, target_commit_sha=commit_sha,
            current_head=current_head, current_step="failed",
        )
        logger.error(f"Health refresh failed for {repo_id} (job={job_id}): {error_msg}")
