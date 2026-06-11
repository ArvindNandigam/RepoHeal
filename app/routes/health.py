from __future__ import annotations

from fastapi import APIRouter, Request

from app.config import get_settings
from app.dependencies import get_operational_repository

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request) -> dict:
    settings = get_settings()
    operational_repository = get_operational_repository()
    start_time = getattr(request.app.state, "start_time", None)
    now = getattr(request.state, "now", None)
    uptime_seconds = int((now - start_time).total_seconds()) if start_time is not None and now is not None else 0
    mongodb_connected = bool(getattr(operational_repository, "is_mongo_connected", True))

    try:
        if mongodb_connected:
            operational_repository.ping()
    except Exception:
        mongodb_connected = False

    return {
        "status": "healthy",
        "mongodb": "connected" if mongodb_connected else "disconnected",
        "cache_expiry_days": settings.cache_expiry_days,
        "service_version": settings.service_version,
        "uptime_seconds": uptime_seconds,
    }

from fastapi import Response

@router.head("/healthz")
def healthz_head():
    return Response(status_code=200)
