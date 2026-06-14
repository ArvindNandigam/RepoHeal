from typing import Optional
from app.config import settings
from fastapi import APIRouter, Depends, Query, Request, Response
from app.errors.exceptions import GraphError, RepositoryNotFoundError
from fastapi.responses import HTMLResponse
from app.auth.jwt_manager import verify_session_token
from app.auth.authorization import verify_repository_access
from app.routers.dependencies import get_session_data, ensure_repoheal_installed, load_cached_analysis
from app.github.client import RepoHealGitHubClient
from app.github.metadata_branch import MetadataBranchManager
from app.visualization.graph_api import GraphVisualizer
from app.visualization.page_renderer import build_graph_page
from app.utils.logger import get_logger
from app.utils.rate_limit import limiter

try:
    from app.visualization.export_png import render_graph_png
except Exception:
    render_graph_png = None

logger = get_logger(__name__)

router = APIRouter(prefix="/visualize", tags=["visualization"])

@router.get("/{repo_owner}/{repo_name}/export.png")
@limiter.limit("10/minute")
async def visualize_repository_export_png(
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

    if render_graph_png is None:
        raise GraphError(message="Server-side export not available: Playwright not installed")

    try:
        analysis = load_cached_analysis(repo_owner, repo_name)
        graph = None

        if analysis and analysis.get("imports", {}).get("files"):
            visualizer = GraphVisualizer(analysis)
            graph = visualizer.to_cytoscape_format(repo_id)

        if not graph or not graph.get("nodes"):
            github_client = RepoHealGitHubClient(installation["id"])
            repo = github_client.get_repo(repo_id)
            graph = MetadataBranchManager(github_client).load_latest_graph(repo)

        if not graph or not graph.get("nodes"):
            raise RepositoryNotFoundError(message="No graph data found. Run /analyze first.")

        png = await render_graph_png(graph)
        return Response(content=png, media_type="image/png")
    except RepositoryNotFoundError:
        raise
    except Exception as e:
        logger.error(f"Failed to export PNG for {repo_id}: {e}")
        raise GraphError(message=str(e))

@router.get("/{repo_owner}/{repo_name}")
@limiter.limit("30/minute")
async def visualize_repository_page(
    request: Request,
    repo_owner: str,
    repo_name: str,
    analysis_id: Optional[str] = Query(None),
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    ensure_repoheal_installed(repo_owner, repo_name)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )

    return HTMLResponse(
        build_graph_page(
            repo_owner=repo_owner,
            repo_name=repo_name,
            github_user=user["github_login"],
            analysis_id=analysis_id,
            feedback_link=settings.FEEDBACK_LINK
        )
    )
