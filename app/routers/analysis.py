from datetime import datetime, timezone
from app.models.schemas import (
    AnalysisResponse,
    AnalysisTarget,
    CompareAnalysesRequest,
    CompareAnalysesResponse,
    SimulateUpgradeRequest,
    SimulateUpgradeResponse,
    SimulatedUpgradeResult,
)
from fastapi import APIRouter, Depends, Request, BackgroundTasks, Body, Query
from app.errors.exceptions import AnalysisError, RepositoryNotFoundError
from app.auth.jwt_manager import verify_session_token
from app.auth.authorization import verify_repository_access
from app.routers.dependencies import get_session_data, ensure_repoheal_installed
from app.utils.rate_limit import limiter
from app.worker.task_registry import (
    create_job,
    get_job,
    get_active_jobs,
    run_analysis_in_background,
    run_health_refresh_in_background,
)
from typing import Dict, Any
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["analysis"])


def _normalize_target(
    mode: str = "latest",
    branch: str | None = None,
    commit_sha: str | None = None
) -> AnalysisTarget:
    selected_mode = (mode or "latest").strip().lower()
    if selected_mode not in {"latest", "branch", "commit"}:
        selected_mode = "latest"
    return AnalysisTarget(
        mode=selected_mode,
        branch=(branch or None),
        commit_sha=(commit_sha or None)
    )


def _target_from_body(body: AnalysisTarget | None) -> AnalysisTarget:
    if not body:
        return _normalize_target()
    return _normalize_target(body.mode, body.branch, body.commit_sha)

@router.get("/analyze/{repo_owner}/{repo_name}", response_model=AnalysisResponse)
@limiter.limit("10/minute")
async def analyze_repository_endpoint(
    request: Request,
    repo_owner: str,
    repo_name: str,
    background_tasks: BackgroundTasks,
    mode: str = Query("latest"),
    branch: str | None = Query(None),
    commit_sha: str | None = Query(None),
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    ensure_repoheal_installed(repo_owner, repo_name)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )

    repo_id = f"{repo_owner}/{repo_name}"
    logger.info(f"Analysis requested for: {repo_id}")

    try:
        target = _normalize_target(mode, branch, commit_sha)
        job_id = create_job(
            repo_owner,
            repo_name,
            target_mode=target.mode,
            target_branch=target.branch,
            target_commit_sha=target.commit_sha
        )
        if job_id:
            background_tasks.add_task(
                run_analysis_in_background,
                job_id,
                repo_owner,
                repo_name,
                False,
                target.branch,
                target.commit_sha
            )
            logger.info(f"Analysis job {job_id} dispatched for: {repo_id}")
        else:
            logger.info(f"Analysis already queued or running for: {repo_id}")

        return AnalysisResponse(
            repository=repo_id,
            status="queued",
            analysis={
                "job_id": job_id,
                "deduplicated": job_id is None,
                "mode": target.mode,
                "branch": target.branch,
                "commit_sha": target.commit_sha
            },
            graph_url=f"/graph/{repo_owner}/{repo_name}",
            visualize_url=f"/visualize/{repo_owner}/{repo_name}",
            timestamp=datetime.utcnow().isoformat()
        )
    except Exception as e:
        logger.error(f"Analysis failed to queue for {repo_id}: {e}")
        raise AnalysisError(message=str(e))

@router.post("/reanalyze/{repo_owner}/{repo_name}")
@limiter.limit("5/minute")
async def reanalyze_repository_endpoint(
    request: Request,
    repo_owner: str,
    repo_name: str,
    background_tasks: BackgroundTasks,
    target_body: AnalysisTarget | None = Body(None),
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    ensure_repoheal_installed(repo_owner, repo_name)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )

    target = _target_from_body(target_body)
    job_id = create_job(
        repo_owner,
        repo_name,
        force=True,
        job_type="reanalyze",
        target_mode=target.mode,
        target_branch=target.branch,
        target_commit_sha=target.commit_sha
    )
    if job_id:
        background_tasks.add_task(
            run_analysis_in_background,
            job_id,
            repo_owner,
            repo_name,
            True,
            target.branch,
            target.commit_sha
        )
        logger.info(f"Full reanalysis job {job_id} dispatched for {repo_owner}/{repo_name}")

    return {
        "status": "queued",
        "message": "Full repository reanalysis scheduled",
        "job_id": job_id,
        "deduplicated": job_id is None,
        "mode": target.mode,
        "branch": target.branch,
        "commit_sha": target.commit_sha
    }


@router.post("/health-refresh/{repo_owner}/{repo_name}")
@limiter.limit("5/minute")
async def health_refresh_repository_endpoint(
    request: Request,
    repo_owner: str,
    repo_name: str,
    background_tasks: BackgroundTasks,
    target_body: AnalysisTarget | None = Body(None),
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    ensure_repoheal_installed(repo_owner, repo_name)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )

    target = _target_from_body(target_body)
    job_id = create_job(
        repo_owner,
        repo_name,
        force=True,
        job_type="health_refresh",
        target_mode=target.mode,
        target_branch=target.branch,
        target_commit_sha=target.commit_sha
    )
    if job_id:
        background_tasks.add_task(
            run_health_refresh_in_background,
            job_id,
            repo_owner,
            repo_name,
            target.branch,
            target.commit_sha
        )
        logger.info(f"Health refresh job {job_id} dispatched for {repo_owner}/{repo_name}")

    return {
        "status": "queued",
        "message": "Health refresh scheduled",
        "job_id": job_id,
        "deduplicated": job_id is None,
        "mode": target.mode,
        "branch": target.branch,
        "commit_sha": target.commit_sha
    }


@router.get("/reports/{repo_owner}/{repo_name}", response_model=Dict[str, Any])
@limiter.limit("20/minute")
async def latest_report_endpoint(
    request: Request,
    repo_owner: str,
    repo_name: str,
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    installation = ensure_repoheal_installed(repo_owner, repo_name)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )

    repo_id = f"{repo_owner}/{repo_name}"
    try:
        from app.github.client import RepoHealGitHubClient
        from app.github.metadata_branch import MetadataBranchManager

        github_client = RepoHealGitHubClient(installation["id"])
        repo = github_client.get_repo(repo_id)
        report = MetadataBranchManager(github_client).load_latest_report(repo)
        if not report:
            raise RepositoryNotFoundError(message="No health report found")
        return report
    except RepositoryNotFoundError:
        raise
    except Exception as e:
        logger.error(f"Report lookup failed for {repo_id}: {e}")
        raise AnalysisError(message=str(e))


@router.post("/compare/{repo_owner}/{repo_name}", response_model=CompareAnalysesResponse)
@limiter.limit("5/minute")
async def compare_analyses_endpoint(
    request: Request,
    repo_owner: str,
    repo_name: str,
    comparison: CompareAnalysesRequest,
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    installation = ensure_repoheal_installed(repo_owner, repo_name)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )

    repo_id = f"{repo_owner}/{repo_name}"
    try:
        from app.github.client import RepoHealGitHubClient
        from app.github.metadata_branch import MetadataBranchManager

        github_client = RepoHealGitHubClient(installation["id"])
        repo = github_client.get_repo(repo_id)
        metadata_manager = MetadataBranchManager(github_client)
        
        manifest = metadata_manager._load_manifest(repo)
        
        def find_id(branch, commit):
            matches = [a for a in manifest.get("analyses", []) if a.get("branch") == branch and a.get("commit", "").startswith(commit)]
            return matches[0]["analysis_id"] if matches else None

        left_id = find_id(comparison.branch_a, comparison.commit_a)
        right_id = find_id(comparison.branch_b, comparison.commit_b)
        
        if left_id and right_id:
            result = metadata_manager.compare_analyses_by_id(repo, left_id, right_id)
            return {
                "repository": repo_id,
                "comparison_id": result.get("comparison_id", ""),
                "delta": result
            }
        
        comparison_path, payload = metadata_manager.compare_analyses_by_branch(
            repo,
            repo_id,
            comparison.branch_a,
            comparison.commit_a,
            comparison.branch_b,
            comparison.commit_b
        )
        return {
            "repository": repo_id,
            "comparison_path": comparison_path,
            "comparison": payload
        }
    except ValueError as e:
        msg = str(e)
        logger.warning(f"Comparison failed for {repo_id}: {msg}")
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=404,
            content={
                "error": "comparison_unavailable",
                "detail": "Comparison unavailable.",
                "reason": "One or more analysis records do not exist.",
                "required_action": "Run analysis for both commits before comparison.",
                "message": msg,
            }
        )
    except Exception as e:
        logger.error(f"Comparison failed for {repo_id}: {e}")
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=500,
            content={
                "error": "comparison_failed",
                "detail": "Comparison failed.",
                "reason": str(e),
                "required_action": "Check server logs for details.",
            }
        )


@router.post("/analyze/simulate/{repo_owner}/{repo_name}")
@limiter.limit("10/minute")
async def simulate_upgrades_endpoint(
    request: Request,
    repo_owner: str,
    repo_name: str,
    simulation: SimulateUpgradeRequest,
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    installation = ensure_repoheal_installed(repo_owner, repo_name)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )

    repo_id = f"{repo_owner}/{repo_name}"
    logger.info(f"Upgrade simulation requested for {repo_id}")

    try:
        from app.github.client import RepoHealGitHubClient
        from app.github.metadata_branch import MetadataBranchManager
        from app.intelligence.webtool_client import WebtoolClient
        from app.graph.connection import neo4j_connection

        github_client = RepoHealGitHubClient(installation["id"])
        repo = github_client.get_repo(repo_id)
        metadata = MetadataBranchManager(github_client)
        manifest = metadata._load_manifest(repo)

        latest_analysis_id = manifest.get("latest_analysis_id")
        if not latest_analysis_id:
            raise AnalysisError(message="No analysis found for this repository")

        analysis_meta = next((a for a in manifest.get("analyses", []) if a["analysis_id"] == latest_analysis_id), None)
        if not analysis_meta:
            raise AnalysisError(message="Latest analysis metadata not found")

        analysis_record = metadata.load_analysis_record(repo, analysis_meta.get("branch", "main"), analysis_meta.get("commit", ""))
        if not analysis_record:
            raise AnalysisError(message="Analysis data could not be loaded from metadata branch")

        analysis = analysis_record.get("analysis", {})
        fingerprints = analysis.get("fingerprints", {})
        dependency_graph = analysis.get("dependency_graph", {})
        semantic_files = analysis.get("semantic_graph", {}).get("files", {})

        webtool = WebtoolClient()
        results = []

        for upgrade in simulation.upgrades:
            library = upgrade.library
            fp_data = fingerprints.get(library, {})
            symbols = fp_data.get("symbols", [])
            installed_version = fp_data.get("version", upgrade.from_version)

            if not symbols:
                results.append(SimulatedUpgradeResult(
                    library=library,
                    from_version=upgrade.from_version,
                    to_version=upgrade.to_version,
                    symbol_count=0,
                    impacted_files=[],
                    breaking_apis=[],
                    auto_fixable_count=0,
                    manual_review_count=0,
                    risk_score=0.0,
                    risk_level="none"
                ))
                continue

            try:
                intelligence = await webtool.get_library_intelligence(library, upgrade.to_version)
            except Exception as e:
                logger.warning(f"Could not fetch intelligence for {library}@{upgrade.to_version}: {e}")
                results.append(SimulatedUpgradeResult(
                    library=library,
                    from_version=upgrade.from_version,
                    to_version=upgrade.to_version,
                    symbol_count=len(symbols),
                    impacted_files=[],
                    breaking_apis=[],
                    auto_fixable_count=0,
                    manual_review_count=len(symbols),
                    risk_score=50.0,
                    risk_level="medium"
                ))
                continue

            impacting_results = intelligence.get("results", [])
            breaking_apis = []
            auto_fixable = 0
            manual_review = 0
            impacted_file_set = set()
            total_confidence = 0.0
            confidence_count = 0

            for result_entry in impacting_results:
                symbol_name = result_entry.get("symbol")
                relationships = result_entry.get("relationships", [])

                for rel in relationships:
                    conf = rel.get("confidence")
                    if isinstance(conf, (int, float)):
                        total_confidence += float(conf)
                        confidence_count += 1

                    if rel.get("relation") in ("removed_in", "breaking_change"):
                        breaking_apis.append(symbol_name)
                        if rel.get("auto_fixable"):
                            auto_fixable += 1
                        else:
                            manual_review += 1

                    elif rel.get("relation") in ("deprecated_in", "deprecated_in_favor_of"):
                        manual_review += 1

            if not breaking_apis:
                auto_fixable = len(impacting_results)
                manual_review = 0

            with neo4j_connection.get_session() as session:
                for symbol in set(breaking_apis + [r.get("symbol") for r in impacting_results]):
                    result = session.run(
                        """
                        MATCH (fn:Function)-[:USES_API]->(a:API)
                        WHERE a.name CONTAINS $symbol AND a.repo_id = $repo_id
                        RETURN a.file_path AS file_path
                        """,
                        symbol=symbol.split(".")[-1],
                        repo_id=repo_id
                    )
                    for record in result:
                        if record.get("file_path"):
                            impacted_file_set.add(record["file_path"])

            avg_confidence = (total_confidence / confidence_count) if confidence_count > 0 else None
            breaking_count = len(breaking_apis)
            risk_score = min(100.0, breaking_count * 20 + manual_review * 10)
            risk_level = "high" if risk_score >= 70 else ("medium" if risk_score >= 40 else "low")

            results.append(SimulatedUpgradeResult(
                library=library,
                from_version=upgrade.from_version,
                to_version=upgrade.to_version,
                symbol_count=len(symbols),
                impacted_files=sorted(impacted_file_set),
                breaking_apis=breaking_apis,
                auto_fixable_count=auto_fixable,
                manual_review_count=manual_review,
                risk_score=risk_score,
                risk_level=risk_level,
                confidence=avg_confidence
            ))

        await webtool.close()

        overall_risk = max((r.risk_score for r in results), default=0.0)
        overall_level = "high" if overall_risk >= 70 else ("medium" if overall_risk >= 40 else "low")

        # Record upgrade simulation metrics
        from app.worker.metrics import record_migration_metrics
        auto_fix_total = sum(r.auto_fixable_count for r in results)
        record_migration_metrics(reports=0, simulations=len(results), auto_fixes=auto_fix_total)

        return SimulateUpgradeResponse(
            repository=repo_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            analysis_id=latest_analysis_id,
            upgrades=results,
            overall_risk_score=overall_risk,
            overall_risk_level=overall_level
        )

    except RepositoryNotFoundError:
        raise
    except AnalysisError:
        raise
    except Exception as e:
        logger.error(f"Simulation failed for {repo_id}: {e}")
        raise AnalysisError(message=str(e))


@router.get("/jobs/queue", response_model=Dict[str, Any])
async def get_job_queue(user=Depends(verify_session_token)):
    """Return all active jobs across all repositories (auto-recovery aware)."""
    return {
        "active_jobs": get_active_jobs(),
        "total_active": len(get_active_jobs()),
    }


@router.get("/jobs/{job_id}", response_model=Dict[str, Any])
async def get_job_status_endpoint(
    job_id: str,
    user=Depends(verify_session_token),
):
    """Return status of a specific job by ID."""
    job = get_job(job_id)
    if not job:
        raise AnalysisError(message="Job not found")
    return job
