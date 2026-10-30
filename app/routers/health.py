import jwt
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from app.config import settings
from app.models.schemas import HealthResponse
from app.db.database import check_mongo_health
from app.graph.connection import neo4j_connection

router = APIRouter(tags=["health"])

@router.get("/")
def root(request: Request = None):
    destination = "/auth/login-page"
    token = request.cookies.get("repoheal_session") if request else None
    if token:
        try:
            jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=["HS256"])
            destination = "/dashboard"
        except jwt.PyJWTError:
            pass
    return RedirectResponse(url=destination, status_code=307)

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
