from fastapi import APIRouter
from app.models.schemas import HealthResponse
from app.db.database import check_mongo_health

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
        "mongodb": "healthy" if check_mongo_health() else "unhealthy"
    }
