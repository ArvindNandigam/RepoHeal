from datetime import datetime, timedelta, timezone
from typing import Union
from fastapi import APIRouter, Depends, Request
from app.errors.exceptions import GraphError, RepositoryNotFoundError
from app.models.schemas import GraphResponse, GraphBuildingResponse, RepositoryStatus
from app.auth.jwt_manager import verify_session_token
from app.auth.authorization import verify_repository_access
from app.routers.dependencies import (
    get_session_data,
    ensure_repoheal_installed,
    load_cached_analysis
)

from app.visualization.graph_api import GraphVisualizer
from app.graph.connection import neo4j_connection
from app.utils.logger import get_logger
from app.utils.rate_limit import limiter
from app.worker.task_registry import get_repository_status as get_analysis_status

logger = get_logger(__name__)

router = APIRouter(tags=["graph"])


def _is_stale_finalizing_status(status: dict) -> bool:
    if status.get("status") != "running" or status.get("progress", 0) < 90:
        return False

    updated_at = status.get("updated_at")
    if not updated_at:
        return False

    try:
        parsed = datetime.fromisoformat(updated_at)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return False

    return parsed <= datetime.now(timezone.utc) - timedelta(minutes=5)


@router.get("/graph/{repo_owner}/{repo_name}", response_model=Union[GraphResponse, GraphBuildingResponse])
@limiter.limit("30/minute")
async def get_graph_visualization(
    request: Request,
    repo_owner: str,
    repo_name: str,
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

    logger.info(f"Graph visualization requested for: {repo_id}")

    try:
        analysis_status = get_analysis_status(repo_owner, repo_name)
        if (
            analysis_status["status"] in {"queued", "running", "failed"}
            and not _is_stale_finalizing_status(analysis_status)
        ):
            return {
                "repository": repo_id,
                "status": "building",
                "progress": analysis_status["progress"],
                "message": analysis_status["message"]
            }

        analysis = load_cached_analysis(
            repo_owner,
            repo_name
        )

        if not analysis:
            return {
                "repository": repo_id,
                "status": "building",
                "progress": analysis_status["progress"],
                "message": analysis_status["message"]
            }

        if not analysis.get("imports", {}).get("files"):
            return {
                "repository": repo_id,
                "status": "building",
                "progress": analysis_status["progress"],
                "message": analysis_status["message"]
            }

        visualizer = GraphVisualizer(analysis)
        graph = visualizer.to_cytoscape_format(repo_id)

        return {
            "repository": repo_id,
            **graph,
            "statistics": visualizer.get_statistics()
        }
    except RepositoryNotFoundError:
        raise
    except Exception as e:
        logger.error(f"Graph visualization failed for {repo_id}: {e}")
        raise GraphError(message=str(e))

@router.get("/status/{repo_owner}/{repo_name}", response_model=RepositoryStatus)
@limiter.limit("30/minute")
async def get_repository_status(
    request: Request,
    repo_owner: str,
    repo_name: str,
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

    logger.info(f"Status requested for: {repo_id}")

    try:
        analysis_status = get_analysis_status(repo_owner, repo_name)
        should_check_graph = (
            analysis_status["status"] in {"completed", "not_started"}
            or _is_stale_finalizing_status(analysis_status)
        )
        if not should_check_graph:
            return {
                "repository": repo_id,
                "status": analysis_status["status"],
                "progress": analysis_status["progress"],
                "message": analysis_status["message"]
            }

        with neo4j_connection.get_session() as session:
            result = session.run(
                """
                MATCH (r:Repository {id: $repo_id})
                OPTIONAL MATCH (r)-[:CONTAINS]->(f:File)
                OPTIONAL MATCH (f)-[:IMPORTS]->(p:Package)
                RETURN count(distinct f) as file_count, count(distinct p) as package_count
                """,
                repo_id=repo_id
            )
            record = result.single()

            if not record:
                return {
                    "repository": repo_id,
                    "status": analysis_status["status"],
                    "progress": analysis_status["progress"],
                    "message": analysis_status["message"]
                }

            file_count = record["file_count"]
            package_count = record["package_count"]
            if (
                analysis_status["status"] == "not_started"
                and file_count == 0
                and package_count == 0
            ):
                return {
                    "repository": repo_id,
                    "status": "not_started",
                    "progress": 0,
                    "message": "Analysis has not started",
                    "files": 0,
                    "packages": 0
                }

            if file_count == 0 and package_count == 0:
                return {
                    "repository": repo_id,
                    "status": analysis_status["status"],
                    "progress": analysis_status["progress"],
                    "message": analysis_status["message"],
                    "files": 0,
                    "packages": 0
                }

            return {
                "repository": repo_id,
                "status": "completed",
                "progress": 100,
                "message": "Analysis complete",
                "files": file_count,
                "packages": package_count
            }
    except Exception as e:
        logger.error(f"Status endpoint failed for {repo_id}: {e}")
        raise GraphError(message=str(e))
