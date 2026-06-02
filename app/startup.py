from __future__ import annotations

import logging
from uuid import uuid4

from app.config import Settings
from app.knowledge.repository import KnowledgeRepository
from app.observability.repository import OperationalRepository

logger = logging.getLogger(__name__)

def validate_startup_settings(settings: Settings) -> None:
    if not settings.internal_api_key or len(settings.internal_api_key) < 32:
        raise ValueError("INTERNAL_API_KEY is required and must be long enough")
    if not settings.allowed_domains:
        raise ValueError("ALLOWED_DOMAINS must not be empty")

def initialize_runtime(operational_repository: OperationalRepository, knowledge_repository: KnowledgeRepository, settings: Settings) -> None:
    try:
        operational_repository.ping()
        knowledge_repository.ensure_indexes()
        operational_repository.ensure_collections()
        validate_startup_settings(settings)
        operational_repository.ensure_api_key("repoheal-agent", settings.internal_api_key or "")
        operational_repository.log_audit_event(
            event="startup",
            request_id=str(uuid4()),
            library=None,
            details={"service_version": settings.service_version},
        )
    except Exception as exc:
        logger.exception("startup initialization failed: %s", exc)
