from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import (
    FastAPI,
    Request,
    HTTPException
)
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.github.webhooks import (
    verify_github_signature
)

from app.github.repository_fetcher import (
    download_repository_snapshot,
    cleanup_repository
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

logger = get_logger(__name__)
templates = Jinja2Templates(directory="app/visualization/templates")
REPO_CACHE_ROOT = Path(".repoheal_cache")


@asynccontextmanager
async def lifespan(app: FastAPI):

    logger.info("Starting RepoHeal backend")

    neo4j_connection.connect()

    yield

    neo4j_connection.close()

    logger.info("Shutting down RepoHeal backend")


app = FastAPI(lifespan=lifespan)


def get_repo_cache_path(repo_owner: str, repo_name: str) -> Path:

    return REPO_CACHE_ROOT / repo_owner / repo_name


def load_cached_analysis(repo_owner: str, repo_name: str):

    cache_store = MetadataStore(str(get_repo_cache_path(repo_owner, repo_name)))

    imports = cache_store.load_imports() or {"files": {}, "summary": {}}
    dependencies = cache_store.load_packages() or {"declared": {}, "count": 0}
    dependency_graph = cache_store.load_dependency_graph() or {}
    summary = cache_store.load_analysis_snapshot() or {}

    return {
        "imports": imports,
        "dependencies": dependencies,
        "dependency_graph": dependency_graph,
        "issues": summary.get("issues", {})
    }


@app.get("/")
def root():

    return {
        "status": "RepoHeal running",
        "version": "1.0",
        "architecture": (
            "On-demand repository intelligence system"
        ),
        "features": [
            "GitHub App",
            "Webhook Verification",
            "AST Import Analysis",
            "Dependency Detection",
            "Neo4j Knowledge Graph",
            "Repository Visualization"
        ],
        "endpoints": {
            "analyze": (
                "/analyze/{repo_owner}/{repo_name}"
            ),
            "graph": (
                "/graph/{repo_owner}/{repo_name}"
            ),
            "visualize": (
                "/visualize/{repo_owner}/{repo_name}"
            ),
            "status": (
                "/status/{repo_owner}/{repo_name}"
            ),
            "webhook": (
                "/webhook/github"
            ),
            "graph_test": (
                "/graph-test"
            )
        }
    }


@app.post("/webhook/github")
async def github_webhook(request: Request):

    """
    GitHub App webhook endpoint.

    Handles:
    - push
    - installation
    - pull_request
    - check_suite

    IMPORTANT:
    Repository analysis is NOT triggered here.
    Analysis only occurs when repository is opened.
    """

    try:

        await verify_github_signature(request)

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

    logger.info(
        f"Received GitHub event: {event_type}"
    )

    if event_type == "push":

        repo_name = (
            payload.get("repository", {})
            .get("name")
        )

        repo_owner = (
            payload.get("repository", {})
            .get("owner", {})
            .get("login")
        )

        logger.info(
            f"Push detected on "
            f"{repo_owner}/{repo_name}"
        )

    elif event_type == "installation":

        action = payload.get("action")

        logger.info(
            f"Installation event: {action}"
        )

    elif event_type == "pull_request":

        action = payload.get("action")

        logger.info(
            f"Pull request event: {action}"
        )

    elif event_type == "check_suite":

        logger.info(
            "Check suite event received"
        )

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
async def analyze_repository_endpoint(
    repo_owner: str,
    repo_name: str
):

    """
    CORE REPOSITORY ANALYSIS ENDPOINT

    Flow:
    1. Download GitHub ZIP snapshot
    2. Extract temporary repository
    3. Perform AST analysis
    4. Detect dependencies
    5. Build Neo4j graph
    6. Cleanup repository snapshot
    """

    repo_id = f"{repo_owner}/{repo_name}"

    logger.info(
        f"Analysis requested for: {repo_id}"
    )

    repo_path = None

    try:

        repo_path = download_repository_snapshot(
            repo_owner,
            repo_name
        )

        analysis = analyze_repository(
            repo_path
        )

        save_analysis_to_metadata(
            str(get_repo_cache_path(repo_owner, repo_name)),
            analysis
        )

        graph_builder = Neo4jGraphBuilder()

        graph_builder.build_graph(
            repo_id,
            analysis
        )

        logger.info(
            f"Analysis completed for: {repo_id}"
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
                datetime.utcnow().isoformat()
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

            cleanup_repository(repo_path)


@app.get(
    "/graph/{repo_owner}/{repo_name}"
)
async def get_graph_visualization(
    repo_owner: str,
    repo_name: str
):

    """
    Returns Cytoscape-compatible graph JSON.
    """

    repo_id = f"{repo_owner}/{repo_name}"

    logger.info(
        f"Graph visualization requested "
        f"for: {repo_id}"
    )

    try:
        analysis = load_cached_analysis(repo_owner, repo_name)

        if not analysis["imports"]["files"]:
            raise HTTPException(
                status_code=404,
                detail=(
                    "No cached analysis found. "
                    "Run /analyze first."
                )
            )

        visualizer = GraphVisualizer(analysis)
        graph = visualizer.to_cytoscape_format(repo_id)

        return {
            "repository": repo_id,
            **graph,
            "statistics": visualizer.get_statistics()
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
async def visualize_repository_page(
    request: Request,
    repo_owner: str,
    repo_name: str
):

    return templates.TemplateResponse(
        "graph.html",
        {
            "request": request,
            "repo_owner": repo_owner,
            "repo_name": repo_name
        }
    )


@app.get(
    "/status/{repo_owner}/{repo_name}"
)
async def get_repository_status(
    repo_owner: str,
    repo_name: str
):

    """
    Repository graph status endpoint.
    """

    repo_id = f"{repo_owner}/{repo_name}"

    logger.info(
        f"Status requested for: {repo_id}"
    )

    try:

        with neo4j_connection.get_session() as session:

            result = session.run(
                """
                MATCH
                    (r:Repository {id: $repo_id})

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
                ),
                "graph_url": (
                    f"/graph/"
                    f"{repo_owner}/{repo_name}"
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


@app.get("/graph-test")
def graph_test():

    """
    Neo4j connectivity test endpoint.
    """

    try:

        with neo4j_connection.get_session() as session:

            result = session.run(
                """
                RETURN
                    'RepoHeal Neo4j Connected'
                    as message
                """
            )

            record = result.single()

            logger.info(
                "Neo4j connectivity test successful"
            )

            return {
                "message": record["message"]
            }

    except Exception as e:

        logger.error(
            f"Neo4j test failed: {e}"
        )

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )