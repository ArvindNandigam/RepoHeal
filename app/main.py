from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
import jwt
from app.auth.authorization import (
    verify_repository_access
)
from fastapi import (
    FastAPI,
    Request,
    HTTPException,
    Depends
)

from fastapi.responses import (
    HTMLResponse,
    RedirectResponse
)

from fastapi.templating import (
    Jinja2Templates
)

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware

from app.auth.github_oauth import (
    router as auth_router
)

from app.auth.session_store import (
    session_store
)

from app.auth.jwt_manager import (
    verify_session_token
)

from app.github.webhooks import (
    verify_github_signature
)

from app.github.repository_fetcher import (
    download_repository_snapshot,
    cleanup_repository
)

from app.github.user_repositories import (
    fetch_user_repositories
)

from app.github.client import (
    RepoHealGitHubClient
)

from app.github.installations import (
    get_repository_installation
)

from app.analysis.repository_analyzer import (
    analyze_repository
)

from app.storage.metadata_store import (
    MetadataStore,
    save_analysis_to_metadata
)

from app.visualization.graph_api import (
    GraphVisualizer
)

from app.graph.connection import (
    neo4j_connection
)

from app.graph.graph_builder import (
    Neo4jGraphBuilder
)

from app.utils.logger import (
    get_logger
)
from app.config import (
    settings
)

logger = get_logger(__name__)

templates = Jinja2Templates(
    directory="app/visualization/templates"
)

REPO_CACHE_ROOT = Path(
    ".repoheal_cache"
)


def sanitize_repo_component(value: str) -> str:

    import re

    return re.sub(r"[^a-zA-Z0-9_.-]", "_", value)

limiter = Limiter(
    key_func=get_remote_address
)


@asynccontextmanager
async def lifespan(app: FastAPI):

    logger.info(
        "Starting RepoHeal backend"
    )

    neo4j_connection.connect()
    session_store.cleanup_expired_sessions()

    yield

    neo4j_connection.close()

    logger.info(
        "Shutting down RepoHeal backend"
    )


app = FastAPI(
    lifespan=lifespan
)

# ---------------------------
# Middleware
# ---------------------------

app.state.limiter = limiter

app.add_middleware(
    SlowAPIMiddleware
)

# ---------------------------
# OAuth Router
# ---------------------------

app.include_router(
    auth_router,
    prefix="/auth/github",
    tags=["auth"]
)


# ---------------------------
# Helpers
# ---------------------------

def get_repo_cache_path(
    repo_owner: str,
    repo_name: str
) -> Path:

    return (
        REPO_CACHE_ROOT
        / sanitize_repo_component(repo_owner)
        / sanitize_repo_component(repo_name)
    )


def ensure_repoheal_installed(
    repo_owner: str,
    repo_name: str
):

    installation = get_repository_installation(
        repo_owner,
        repo_name
    )

    if not installation:
        raise HTTPException(
            status_code=403,
            detail="RepoHeal is not installed on this repository"
        )

    return installation


def load_cached_analysis(
    repo_owner: str,
    repo_name: str
):

    cache_store = MetadataStore(
        str(
            get_repo_cache_path(
                repo_owner,
                repo_name
            )
        )
    )

    imports = (
        cache_store.load_imports()
        or {
            "files": {},
            "summary": {}
        }
    )

    dependencies = (
        cache_store.load_packages()
        or {
            "declared": {},
            "count": 0
        }
    )

    dependency_graph = (
        cache_store.load_dependency_graph()
        or {}
    )

    summary = (
        cache_store.load_analysis_snapshot()
        or {}
    )

    return {
        "imports": imports,
        "dependencies": dependencies,
        "dependency_graph": dependency_graph,
        "issues": summary.get(
            "issues",
            {}
        )
    }


def get_session_data(
    user: dict
):

    session_data = session_store.get_session(
        user["session_id"]
    )

    if not session_data:

        raise HTTPException(
            status_code=401,
            detail="Session expired"
        )

    if session_data.get("github_id") != user.get("github_id"):

        raise HTTPException(
            status_code=401,
            detail="Session mismatch"
        )

    return session_data


# ---------------------------
# Public Endpoints
# ---------------------------

@app.get("/")
def root():

    return {
        "status": "RepoHeal running",
        "version": "1.0",
        "authentication": "GitHub OAuth",
        "documentation": (
            "Login required for protected endpoints"
        ),
        "login_url": "/auth/github/login"
    }


@app.get("/healthz")
def healthz():

    return {
        "status": "healthy"
    }


@app.get(
    "/dashboard/{dashboard_id}",
    response_class=HTMLResponse
)
async def dashboard(
    request: Request,
    dashboard_id: str,
    user=Depends(
        verify_session_token
    )
):

    expected_dashboard = (
        f"{user['github_login']}-repoheal"
    )

    if dashboard_id != expected_dashboard:

        raise HTTPException(
            status_code=403,
            detail="Unauthorized dashboard"
        )

    session_data = (
        session_store.get_session(
            user["session_id"]
        )
    )

    if not session_data:

        raise HTTPException(
            status_code=401,
            detail="Session expired"
        )

    repositories = (
        fetch_user_repositories(
            session_data["github_token"]
        )
    )

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "repositories": repositories
        }
    )


@app.get(
    "/workspace/{repo_owner}/{repo_name}",
    response_class=HTMLResponse
)
async def workspace_landing_page(
    request: Request,
    repo_owner: str,
    repo_name: str,
    user=Depends(
        verify_session_token
    )
):

    session_data = get_session_data(
        user
    )

    ensure_repoheal_installed(
        repo_owner,
        repo_name
    )

    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )

    return templates.TemplateResponse(
        "workspace.html",
        {
            "request": request,
            "repo_owner": repo_owner,
            "repo_name": repo_name,
            "user": user
        }
    )

# ---------------------------
# Protected Endpoints
# ---------------------------

@app.post("/webhook/github")
async def github_webhook(
    request: Request
):

    try:

        await verify_github_signature(
            request
        )

    except Exception as e:

        logger.error(
            f"Webhook verification failed: {e}"
        )

        raise HTTPException(
            status_code=401,
            detail="Invalid GitHub signature"
        )

    payload = await request.json()

    event_type = request.headers.get(
        "X-GitHub-Event"
    )

    event_action = payload.get("action")

    logger.info(
        f"Received GitHub event: "
        f"{event_type} ({event_action})"
    )

    if event_type == "installation" and event_action == "created":

        installation = payload.get("installation") or {}
        installation_id = installation.get("id")

        if not installation_id:
            raise HTTPException(
                status_code=400,
                detail="Missing installation id"
            )

        bootstrap_client = RepoHealGitHubClient(
            installation_id
        )

        bootstrapped_repositories = (
            bootstrap_client.bootstrap_installation_metadata()
        )

        return {
            "received": True,
            "event": event_type,
            "action": event_action,
            "bootstrapped_repositories": (
                bootstrapped_repositories
            ),
            "timestamp": (
                datetime.utcnow().isoformat()
            )
        }

    return {
        "received": True,
        "event": event_type,
        "timestamp": (
            datetime.utcnow().isoformat()
        )
    }


@app.get(
    "/analyze/{repo_owner}/{repo_name}"
)
@limiter.limit("10/minute")
async def analyze_repository_endpoint(
    request: Request,
    repo_owner: str,
    repo_name: str,
    user=Depends(
        verify_session_token
    )
):
    session_data = get_session_data(
        user
    )

    ensure_repoheal_installed(
        repo_owner,
        repo_name
    )

    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )

    repo_id = (
        f"{repo_owner}/{repo_name}"
    )

    logger.info(
        f"Analysis requested for: "
        f"{repo_id}"
    )

    repo_path = None

    try:

        repo_path = (
            download_repository_snapshot(
                repo_owner,
                repo_name
            )
        )

        analysis = analyze_repository(
            repo_path
        )

        save_analysis_to_metadata(
            str(
                get_repo_cache_path(
                    repo_owner,
                    repo_name
                )
            ),
            analysis
        )

        graph_builder = (
            Neo4jGraphBuilder()
        )

        graph_builder.build_graph(
            repo_id,
            analysis
        )

        logger.info(
            f"Analysis completed for: "
            f"{repo_id}"
        )

        return {
            "repository": repo_id,
            "status": "analyzed",
            "analysis": analysis,
            "graph_url": (
                f"/graph/"
                f"{repo_owner}/{repo_name}"
            ),
            "visualize_url": (
                f"/visualize/"
                f"{repo_owner}/{repo_name}"
            ),
            "timestamp": (
                datetime.utcnow()
                .isoformat()
            )
        }

    except Exception as e:

        logger.error(
            f"Analysis failed for "
            f"{repo_id}: {e}"
        )

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:

        if repo_path:

            cleanup_repository(
                repo_path
            )


@app.get(
    "/graph/{repo_owner}/{repo_name}"
)
@limiter.limit("30/minute")
async def get_graph_visualization(
    request: Request,
    repo_owner: str,
    repo_name: str,
    user=Depends(
        verify_session_token
    )
):
    session_data = get_session_data(
        user
    )

    ensure_repoheal_installed(
        repo_owner,
        repo_name
    )

    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )
    repo_id = (
        f"{repo_owner}/{repo_name}"
    )

    logger.info(
        f"Graph visualization requested "
        f"for: {repo_id}"
    )

    try:

        analysis = load_cached_analysis(
            repo_owner,
            repo_name
        )

        if not analysis["imports"]["files"]:

            raise HTTPException(
                status_code=404,
                detail=(
                    "No cached analysis found. "
                    "Run /analyze first."
                )
            )

        visualizer = (
            GraphVisualizer(
                analysis
            )
        )

        graph = (
            visualizer
            .to_cytoscape_format(
                repo_id
            )
        )

        return {
            "repository": repo_id,
            **graph,
            "statistics": (
                visualizer
                .get_statistics()
            )
        }

    except HTTPException:

        raise

    except Exception as e:

        logger.error(
            f"Graph visualization failed "
            f"for {repo_id}: {e}"
        )

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


@app.get(
    "/visualize/{repo_owner}/{repo_name}",
    response_class=HTMLResponse
)
@limiter.limit("30/minute")
async def visualize_repository_page(
    request: Request,
    repo_owner: str,
    repo_name: str,
    user=Depends(
        verify_session_token
    )
):
    session_data = get_session_data(
        user
    )

    ensure_repoheal_installed(
        repo_owner,
        repo_name
    )

    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )
    return templates.TemplateResponse(
        "graph.html",
        {
            "request": request,
            "repo_owner": repo_owner,
            "repo_name": repo_name,
            "github_user": (
                user["github_login"]
            )
        }
    )


@app.get(
    "/status/{repo_owner}/{repo_name}"
)
@limiter.limit("30/minute")
async def get_repository_status(
    request: Request,
    repo_owner: str,
    repo_name: str,
    user=Depends(
        verify_session_token
    )
):
    session_data = get_session_data(
        user
    )

    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )
    repo_id = (
        f"{repo_owner}/{repo_name}"
    )

    logger.info(
        f"Status requested for: "
        f"{repo_id}"
    )

    try:

        with neo4j_connection.get_session() as session:

            result = session.run(
                """
                MATCH
                    (r:Repository {
                        id: $repo_id
                    })

                OPTIONAL MATCH
                    (r)-[:CONTAINS]->
                    (m:Module)

                OPTIONAL MATCH
                    (m)-[:IMPORTS]->
                    (p:Package)

                RETURN
                    count(distinct m)
                        as module_count,

                    count(distinct p)
                        as package_count
                """,
                repo_id=repo_id
            )

            record = result.single()

            if not record:

                return {
                    "repository": repo_id,
                    "status": "not_analyzed"
                }

            return {
                "repository": repo_id,
                "status": "analyzed",
                "modules": (
                    record["module_count"]
                ),
                "packages": (
                    record["package_count"]
                )
            }

    except Exception as e:

        logger.error(
            f"Status endpoint failed "
            f"for {repo_id}: {e}"
        )

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


@app.get("/logout")
async def logout(
    request: Request
):

    token = request.cookies.get(
        "repoheal_session"
    )

    response = RedirectResponse(
        url="/"
    )

    if token:

        try:

            decoded = jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=["HS256"]
            )

            session_id = decoded.get(
                "session_id"
            )

            if session_id:

                session_store.delete_session(
                    session_id
                )

        except Exception:

            pass

    response.delete_cookie(
        "repoheal_session"
    )

    logger.info(
        "User logged out"
    )

    return response