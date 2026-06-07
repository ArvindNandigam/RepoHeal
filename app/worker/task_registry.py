import uuid
import traceback
import shutil
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

from app.db.database import get_mongo_db
from app.utils.logger import get_logger

logger = get_logger(__name__)


class JobStatus(str, Enum):
    NOT_STARTED = "not_started"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    EXTRACTING = "extracting"
    ANALYZING = "analyzing"
    BUILDING_GRAPH = "building_graph"
    WRITING_METADATA = "writing_metadata"
    GENERATING_REPORTS = "generating_reports"
    COMPLETED = "completed"
    FAILED = "failed"


ACTIVE_STATUSES = {
    JobStatus.QUEUED.value,
    JobStatus.DOWNLOADING.value,
    JobStatus.EXTRACTING.value,
    JobStatus.ANALYZING.value,
    JobStatus.BUILDING_GRAPH.value,
    JobStatus.WRITING_METADATA.value,
    JobStatus.GENERATING_REPORTS.value,
}


def create_job(
    repo_owner: str,
    repo_name: str,
    skip_if_recent: bool = False,
    recent_hours: int = 24,
    force: bool = False,
    job_type: str = "analysis"
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
        "status": JobStatus.QUEUED.value,
        "progress": 0,
        "message": _queued_message(job_type),
        "result": None,
        "error": None,
        "created_at": now,
        "updated_at": now,
        "expires_at": now + timedelta(hours=24),
    })
    update_repository_status(
        repo_owner,
        repo_name,
        JobStatus.QUEUED,
        0,
        _queued_message(job_type),
        job_id=job_id,
        job_type=job_type
    )
    return job_id


def _queued_message(job_type: str) -> str:
    if job_type == "health_refresh":
        return "Health refresh queued"
    if job_type == "reanalyze":
        return "Full repository reanalysis queued"
    return "Repository analysis queued"


def update_job(
    job_id: str,
    status: JobStatus,
    result=None,
    error=None,
    progress: int | None = None,
    message: str | None = None
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
    db.jobs.update_one({"job_id": job_id}, {"$set": update})


def update_repository_status(
    repo_owner: str,
    repo_name: str,
    status: JobStatus,
    progress: int,
    message: str,
    job_id: str | None = None,
    error: str | None = None,
    job_type: str | None = None
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
    if error is not None:
        update["error"] = error
    if status == JobStatus.COMPLETED:
        update["completed_at"] = now
        if job_type == "health_refresh":
            update["last_health_refresh"] = now
        else:
            update["last_analysis"] = now

    operation = {
        "$set": update,
        "$setOnInsert": {"created_at": now},
    }
    if error is None:
        operation["$unset"] = {"error": ""}

    db.repository_analysis_status.update_one(
        {"repo_owner": repo_owner, "repo_name": repo_name},
        operation,
        upsert=True
    )


def set_analysis_progress(
    job_id: str,
    repo_owner: str,
    repo_name: str,
    status: JobStatus,
    progress: int,
    message: str,
    error: str | None = None,
    job_type: str | None = None
):
    update_job(
        job_id,
        status,
        error=error,
        progress=progress,
        message=message
    )
    update_repository_status(
        repo_owner,
        repo_name,
        status,
        progress,
        message,
        job_id=job_id,
        error=error,
        job_type=job_type
    )


def cancel_repository_jobs(
    repo_owner: str,
    repo_name: str,
    reason: str = "Repository uninstalled"
) -> int:
    """Mark active queued/background jobs as failed so workers stop advertising progress."""
    db = get_mongo_db()
    result = db.jobs.update_many(
        {
            "repo_owner": repo_owner,
            "repo_name": repo_name,
            "status": {"$in": list(ACTIVE_STATUSES)},
        },
        {
            "$set": {
                "status": JobStatus.FAILED.value,
                "progress": 0,
                "message": reason,
                "error": reason,
                "updated_at": datetime.now(timezone.utc),
            }
        }
    )
    update_repository_status(
        repo_owner,
        repo_name,
        JobStatus.FAILED,
        0,
        reason,
        error=reason
    )
    return getattr(result, "modified_count", 0)


def get_repository_status(repo_owner: str, repo_name: str):
    """Return persistent progress, including a not-started default."""
    db = get_mongo_db()
    doc = db.repository_analysis_status.find_one(
        {"repo_owner": repo_owner, "repo_name": repo_name},
        {"_id": 0}
    )
    if not doc:
        return {
            "repository": f"{repo_owner}/{repo_name}",
            "status": JobStatus.NOT_STARTED.value,
            "progress": 0,
            "message": "Analysis has not started",
        }
    for field in (
        "created_at",
        "updated_at",
        "completed_at",
        "last_analysis",
        "last_health_refresh",
    ):
        if isinstance(doc.get(field), datetime):
            doc[field] = doc[field].isoformat()
    return doc


def get_job(job_id: str):
    """Fetch a job by ID."""
    db = get_mongo_db()
    doc = db.jobs.find_one({"job_id": job_id}, {"_id": 0})
    if not doc:
        return None
    # Convert datetimes to ISO strings for JSON serialization
    for field in ("created_at", "updated_at", "expires_at"):
        if isinstance(doc.get(field), datetime):
            doc[field] = doc[field].isoformat()
    return doc


def _clear_local_repository_cache(repo_owner: str, repo_name: str) -> None:
    from app.routers.dependencies import get_repo_cache_path

    cache_path = Path(get_repo_cache_path(repo_owner, repo_name))
    if cache_path.exists():
        shutil.rmtree(cache_path)
        logger.info(f"Cleared local RepoHeal cache at {cache_path}")


def run_analysis_in_background(
    job_id: str,
    repo_owner: str,
    repo_name: str,
    force_reanalysis: bool = False
):
    """
    Synchronous function that runs the full analysis pipeline.
    Called from FastAPI BackgroundTasks.
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
    import asyncio

    repo_id = f"{repo_owner}/{repo_name}"
    repo_path = None
    job_type = "reanalyze" if force_reanalysis else "analysis"

    try:
        if force_reanalysis:
            _clear_local_repository_cache(repo_owner, repo_name)

        set_analysis_progress(
            job_id,
            repo_owner,
            repo_name,
            JobStatus.DOWNLOADING,
            10,
            "Downloading repository",
            job_type=job_type
        )
        logger.info(f"Background analysis started for {repo_id} (job={job_id})")

        repo_path = download_repository_snapshot(repo_owner, repo_name)
        set_analysis_progress(
            job_id,
            repo_owner,
            repo_name,
            JobStatus.EXTRACTING,
            25,
            "Repository extracted",
            job_type=job_type
        )
        set_analysis_progress(
            job_id,
            repo_owner,
            repo_name,
            JobStatus.ANALYZING,
            50,
            "Analyzing repository",
            job_type=job_type
        )
        analysis = analyze_repository(repo_path)
        save_analysis_to_metadata(
            str(get_repo_cache_path(repo_owner, repo_name)),
            analysis
        )

        set_analysis_progress(
            job_id,
            repo_owner,
            repo_name,
            JobStatus.BUILDING_GRAPH,
            75,
            "Building Neo4j graph",
            job_type=job_type
        )
        graph_builder = Neo4jGraphBuilder()
        graph_builder.clear_repository_graph(repo_id)
        graph_builder.build_graph(repo_id, analysis)

        set_analysis_progress(
            job_id,
            repo_owner,
            repo_name,
            JobStatus.WRITING_METADATA,
            90,
            "Updating repoheal.meta branch",
            job_type=job_type
        )
        installation = get_repository_installation(repo_owner, repo_name)
        if not installation or "id" not in installation:
            raise PermissionError(f"RepoHeal is not installed on {repo_id}")

        github_client = RepoHealGitHubClient(installation["id"])
        repo_obj = github_client.get_repo(repo_id)

        from app.github.metadata_branch import MetadataBranchManager
        from app.visualization.graph_api import GraphVisualizer

        visualizer = GraphVisualizer(analysis)
        MetadataBranchManager(github_client).save_latest_analysis(
            repo_obj,
            repo_id,
            analysis,
            {
                **visualizer.to_cytoscape_format(repo_id),
                "statistics": visualizer.get_statistics()
            }
        )

        set_analysis_progress(
            job_id,
            repo_owner,
            repo_name,
            JobStatus.GENERATING_REPORTS,
            95,
            "Generating health reports and migration documents",
            job_type=job_type
        )
        try:
            async def run_pipeline():
                intelligence_provider = create_intelligence_provider()
                pipeline = MigrationPipeline(intelligence_provider, github_client)
                try:
                    report = await pipeline.run(analysis, repo_id, repo_obj)
                    logger.info(f"Migration pipeline finished for {repo_id} with score {report.overall_health_score}")
                finally:
                    await intelligence_provider.close()

            asyncio.run(run_pipeline())
        except Exception as pipeline_err:
            logger.error(f"Migration pipeline failed for {repo_id}: {pipeline_err}")

        update_job(
            job_id,
            JobStatus.COMPLETED,
            result={
                "repository": repo_id,
                "status": "analyzed",
            },
            progress=100,
            message="Analysis complete"
        )
        update_repository_status(
            repo_owner,
            repo_name,
            JobStatus.COMPLETED,
            100,
            "Analysis complete",
            job_id=job_id,
            job_type=job_type
        )
        logger.info(f"Background analysis completed for {repo_id} (job={job_id})")

    except Exception as e:
        error_msg = traceback.format_exc()
        set_analysis_progress(
            job_id,
            repo_owner,
            repo_name,
            JobStatus.FAILED,
            0,
            "Analysis failed",
            error=str(e),
            job_type=job_type
        )
        logger.error(f"Background analysis failed for {repo_id} (job={job_id}): {error_msg}")

    finally:
        if repo_path:
            cleanup_repository(repo_path)


def run_health_refresh_in_background(job_id: str, repo_owner: str, repo_name: str):
    """Refresh migration intelligence using the latest stored analysis snapshot."""
    from app.routers.dependencies import load_cached_analysis
    from app.github.installations import get_repository_installation
    from app.github.client import RepoHealGitHubClient
    from app.intelligence.providers import create_intelligence_provider
    from app.intelligence.pipeline import MigrationPipeline
    import asyncio

    repo_id = f"{repo_owner}/{repo_name}"
    job_type = "health_refresh"

    try:
        set_analysis_progress(
            job_id,
            repo_owner,
            repo_name,
            JobStatus.GENERATING_REPORTS,
            50,
            "Refreshing migration intelligence",
            job_type=job_type
        )
        analysis = load_cached_analysis(repo_owner, repo_name)
        if not analysis or not analysis.get("dependency_graph"):
            raise ValueError("No cached analysis snapshot found for health refresh")

        installation = get_repository_installation(repo_owner, repo_name)
        if not installation or "id" not in installation:
            raise PermissionError(f"RepoHeal is not installed on {repo_id}")

        github_client = RepoHealGitHubClient(installation["id"])
        repo_obj = github_client.get_repo(repo_id)

        async def run_pipeline():
            intelligence_provider = create_intelligence_provider()
            pipeline = MigrationPipeline(intelligence_provider, github_client)
            try:
                return await pipeline.run(analysis, repo_id, repo_obj)
            finally:
                await intelligence_provider.close()

        report = asyncio.run(run_pipeline())
        update_job(
            job_id,
            JobStatus.COMPLETED,
            result={
                "repository": repo_id,
                "status": "health_refreshed",
                "overall_health_score": report.overall_health_score,
            },
            progress=100,
            message="Health refresh complete"
        )
        update_repository_status(
            repo_owner,
            repo_name,
            JobStatus.COMPLETED,
            100,
            "Health refresh complete",
            job_id=job_id,
            job_type=job_type
        )
    except Exception as e:
        error_msg = traceback.format_exc()
        set_analysis_progress(
            job_id,
            repo_owner,
            repo_name,
            JobStatus.FAILED,
            0,
            "Health refresh failed",
            error=str(e),
            job_type=job_type
        )
        logger.error(f"Health refresh failed for {repo_id} (job={job_id}): {error_msg}")
