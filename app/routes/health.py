from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.contracts.schemas import HealthResponseContract
from app.dependencies import get_operational_repository

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponseContract)
def health() -> HealthResponseContract:
    settings = get_settings()
    operational_repository = get_operational_repository()

    try:
        operational_repository.ping()
        return HealthResponseContract(
            status="healthy",
            mongodb="connected",
            cache_expiry_days=settings.cache_expiry_days,
            service_version=settings.service_version,
        )
    except Exception:
        return HealthResponseContract(
            status="unhealthy",
            mongodb="disconnected",
            cache_expiry_days=settings.cache_expiry_days,
            service_version=settings.service_version,
        )

