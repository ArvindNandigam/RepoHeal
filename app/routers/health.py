from fastapi import APIRouter
from app.models.schemas import HealthResponse
from app.db.database import check_mongo_health
from app.graph.connection import neo4j_connection

router = APIRouter(tags=["health"])

@router.get("/", response_model=HealthResponse)
def root():
    return {
        "status": "RepoHeal running",
        "version": "1.0",
        "authentication": "GitHub OAuth",
        "documentation": "Login required for protected endpoints",
        "login_url": "/auth/github/login"
    }

@router.get("/healthz", response_model=HealthResponse)
def healthz():
    return {
        "status": "healthy",
        "mongodb": "healthy" if check_mongo_health() else "unhealthy",
        "neo4j": "healthy" if neo4j_connection.is_available() else "unhealthy"
    }
from fastapi import Response

@router.head("/healthz")
def healthz_head():
    return Response(status_code=200)
