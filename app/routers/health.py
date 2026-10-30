from fastapi import APIRouter
from fastapi.responses import RedirectResponse
from app.models.schemas import HealthResponse
from app.db.database import check_mongo_health
from app.graph.connection import neo4j_connection

router = APIRouter(tags=["health"])

@router.get("/")
def root():
    return RedirectResponse(url="/auth/login-page", status_code=307)

@router.get("/healthz", response_model=HealthResponse)
def healthz():
    mongodb = "connected" if check_mongo_health() else "unavailable"
    neo4j = "connected" if neo4j_connection.is_available() else "unavailable"
    return {
        "status": "healthy" if mongodb == "connected" and neo4j == "connected" else "degraded",
        "mongodb": mongodb,
        "neo4j": neo4j,
    }
from fastapi import Response

@router.head("/healthz")
def healthz_head():
    # Uptime monitors use HEAD as a process liveness check. Dependency
    # degradation is reported by GET /healthz without taking the service down.
    return Response(status_code=200)
