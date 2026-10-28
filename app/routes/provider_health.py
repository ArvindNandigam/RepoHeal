from __future__ import annotations

from fastapi import APIRouter

from app.dependencies import get_operational_repository

router = APIRouter(tags=["health"])


@router.get("/health/providers")
def provider_health() -> dict:
    repository = get_operational_repository()
    providers = {}
    for service in ("mongodb", "pypi", "serper", "groq", "gemini"):
        record = repository.get_service_status(service) or {}
        providers[service] = {
            "status": record.get("status", "unknown"),
            "updated_at": record.get("updated_at"),
            "retry_after": record.get("retry_after"),
        }
    return {"status": "healthy", "providers": providers}
