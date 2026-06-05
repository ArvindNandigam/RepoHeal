from datetime import datetime
from app.models.schemas import AnalysisResponse
from fastapi import APIRouter, Depends, Request, BackgroundTasks
from app.errors.exceptions import AnalysisError, RepositoryNotFoundError
from app.auth.jwt_manager import verify_session_token
from app.auth.authorization import verify_repository_access
from app.routers.dependencies import get_session_data, ensure_repoheal_installed
from app.utils.rate_limit import limiter
from app.worker.task_registry import create_job, get_job, run_analysis_in_background
from typing import Dict, Any
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/analyze", tags=["analysis"])

@router.get("/{repo_owner}/{repo_name}", response_model=AnalysisResponse)
@limiter.limit("10/minute")
async def analyze_repository_endpoint(
    request: Request,
    repo_owner: str,
    repo_name: str,
    background_tasks: BackgroundTasks,
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
        job_id = create_job(repo_owner, repo_name)
        background_tasks.add_task(run_analysis_in_background, job_id, repo_owner, repo_name)
        logger.info(f"Analysis job {job_id} dispatched for: {repo_id}")

        return AnalysisResponse(
            repository=repo_id,
            status="queued",
            analysis={"job_id": job_id},
            graph_url=f"/graph/{repo_owner}/{repo_name}",
            visualize_url=f"/visualize/{repo_owner}/{repo_name}",
            timestamp=datetime.utcnow().isoformat()
        )
    except Exception as e:
        logger.error(f"Analysis failed to queue for {repo_id}: {e}")
        raise AnalysisError(message=str(e))

@router.get("/jobs/{job_id}", response_model=Dict[str, Any])
async def get_job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise RepositoryNotFoundError(message="Job not found")
    return job
