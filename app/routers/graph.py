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

from app.github.client import RepoHealGitHubClient
from app.github.metadata_branch import MetadataBranchManager
from app.visualization.graph_api import GraphVisualizer
from app.graph.connection import neo4j_connection
from app.utils.logger import get_logger
from app.utils.rate_limit import limiter
from app.worker.task_registry import get_repository_status as get_analysis_status

logger = get_logger(__name__)

router = APIRouter(tags=["graph"])


def _is_stale_finalizing_status(status: dict) -> bool:
    if status.get("status") not in {"running", "writing_metadata", "generating_reports"} or status.get("progress", 0) < 90:
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


def _graph_has_nodes(graph: dict | None) -> bool:
    return bool(graph and graph.get("nodes"))


def _is_analysis_incomplete(status: dict) -> bool:
    return status.get("status") not in {"completed", "not_started"}


def _status_metadata(status: dict) -> dict:
    return {
        "last_analysis": status.get("last_analysis"),
        "last_health_refresh": status.get("last_health_refresh"),
        "last_commit_analyzed": status.get("last_commit_analyzed"),
        "current_head": status.get("current_head"),
        "selected_branch": status.get("selected_branch"),
        "code_state_status": status.get("code_state_status"),
    }


def _code_state_metadata(repo_id: str, installation_id: int, status: dict) -> dict:
    selected_branch = status.get("selected_branch")
    current_head = status.get("current_head")
    last_commit = status.get("last_commit_analyzed") or status.get("target_commit_sha")

    try:
        github_client = RepoHealGitHubClient(installation_id)
        repo = github_client.get_repo(repo_id)
        selected_branch = selected_branch or repo.default_branch
        current_head = repo.get_branch(selected_branch).commit.sha
    except Exception as exc:
        logger.warning(f"Could not refresh current HEAD for {repo_id}: {exc}")

    code_state_status = None
    if current_head and last_commit:
        code_state_status = "up_to_date" if current_head == last_commit else "outdated"

    return {
        "last_analysis": status.get("last_analysis"),
        "last_health_refresh": status.get("last_health_refresh"),
        "last_commit_analyzed": last_commit,
        "current_head": current_head,
        "selected_branch": selected_branch,
        "code_state_status": code_state_status,
    }


def _build_cached_graph(repo_id: str, analysis: dict | None) -> dict | None:
    if not analysis or not analysis.get("imports", {}).get("files"):
        return None

    visualizer = GraphVisualizer(analysis)
    graph = visualizer.to_cytoscape_format(repo_id)

    if not _graph_has_nodes(graph):
        return None

    return {
        **graph,
        "statistics": visualizer.get_statistics()
    }


def _build_metadata_graph(repo_id: str, installation_id: int) -> dict | None:
    try:
        github_client = RepoHealGitHubClient(installation_id)
        repo = github_client.get_repo(repo_id)
        graph = MetadataBranchManager(github_client).load_latest_graph(repo)
    except Exception as exc:
        logger.warning(
            f"Could not load metadata branch graph for {repo_id}: {exc}"
        )
        return None

    if not _graph_has_nodes(graph):
        return None

    return {
        "nodes": graph.get("nodes", []),
        "edges": graph.get("edges", []),
        "statistics": graph.get("statistics", {})
    }


@router.get("/graph/{repo_owner}/{repo_name}", response_model=Union[GraphResponse, GraphBuildingResponse])
@limiter.limit("30/minute")
async def get_graph_visualization(
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

    logger.info(f"Graph visualization requested for: {repo_id}")

    try:
        analysis_status = get_analysis_status(repo_owner, repo_name)
        if (
            _is_analysis_incomplete(analysis_status)
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

        cached_graph = _build_cached_graph(repo_id, analysis)
        if cached_graph:
            return {
                "repository": repo_id,
                **cached_graph
            }

        metadata_graph = _build_metadata_graph(repo_id, installation["id"])
        if metadata_graph:
            return {
                "repository": repo_id,
                **metadata_graph
            }

        logger.warning(
            f"No Cytoscape graph data found for {repo_id} in cache or metadata branch"
        )
        return {
            "repository": repo_id,
            "status": "building",
            "progress": analysis_status["progress"],
            "message": analysis_status["message"]
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
    installation = ensure_repoheal_installed(repo_owner, repo_name)
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
                "message": analysis_status["message"],
                **_code_state_metadata(repo_id, installation["id"], analysis_status)
            }

        analysis = load_cached_analysis(repo_owner, repo_name)
        visual_graph = (
            _build_cached_graph(repo_id, analysis)
            or _build_metadata_graph(repo_id, installation["id"])
        )
        missing_graph_response = {
            "repository": repo_id,
            "status": "not_started",
            "progress": 0,
            "message": "Graph snapshot missing; analysis must be rerun",
            "files": 0,
            "packages": 0,
            **_code_state_metadata(repo_id, installation["id"], analysis_status)
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
                if not visual_graph:
                    return missing_graph_response

                return {
                    "repository": repo_id,
                    "status": "completed",
                    "progress": 100,
                    "message": "Analysis complete",
                    "files": 0,
                    "packages": 0,
                    **_code_state_metadata(repo_id, installation["id"], analysis_status)
                }

            file_count = record["file_count"]
            package_count = record["package_count"]
            if not visual_graph:
                return {
                    **missing_graph_response,
                    "files": file_count,
                    "packages": package_count
                }

            return {
                "repository": repo_id,
                "status": "completed",
                "progress": 100,
                "message": "Analysis complete",
                "files": file_count,
                "packages": package_count,
                **_code_state_metadata(repo_id, installation["id"], analysis_status)
            }
    except Exception as e:
        logger.error(f"Status endpoint failed for {repo_id}: {e}")
        raise GraphError(message=str(e))
