from datetime import datetime
from app.models.schemas import (
    AnalysisResponse,
    AnalysisTarget,
    CompareAnalysesRequest,
    CompareAnalysesResponse,
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
        comparison_path, payload = MetadataBranchManager(github_client).compare_analyses(
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
    except Exception as e:
        logger.error(f"Comparison failed for {repo_id}: {e}")
        raise AnalysisError(message=str(e))


@router.get("/analyze/jobs/{job_id}", response_model=Dict[str, Any])
async def get_job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise RepositoryNotFoundError(message="Job not found")
    return job
