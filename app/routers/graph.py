from typing import Union
from app.routers import analysis
from fastapi import APIRouter, Depends, Request
from app.errors.exceptions import GraphError, RepositoryNotFoundError
from app.models.schemas import GraphResponse, GraphBuildingResponse, RepositoryStatus
from app.auth.jwt_manager import verify_session_token
from app.auth.authorization import verify_repository_access
from app.routers.dependencies import get_session_data, ensure_repoheal_installed
from app.visualization.neo4j_graph_api import Neo4jGraphVisualizer
from app.graph.connection import neo4j_connection
from app.utils.logger import get_logger
from app.utils.rate_limit import limiter

logger = get_logger(__name__)

router = APIRouter(tags=["graph"])

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
        graph = Neo4jGraphVisualizer.to_cytoscape_format(repo_id)

        return {
            "repository": repo_id,
            **graph,
            "statistics": {
                "nodes": len(graph["nodes"]),
                "edges": len(graph["edges"])
            }
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
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )
    repo_id = f"{repo_owner}/{repo_name}"

    logger.info(f"Status requested for: {repo_id}")

    try:
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
                    "status": "not_analyzed"
                }

            return {
                "repository": repo_id,
                "status": "analyzed",
                "files": record["file_count"],
                "packages": record["package_count"]
            }
    except Exception as e:
        logger.error(f"Status endpoint failed for {repo_id}: {e}")
        raise GraphError(message=str(e))
