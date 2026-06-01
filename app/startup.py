from __future__ import annotations

import json
import logging
from pathlib import Path
from uuid import uuid4

from app.config import Settings
from app.cache.repository import MongoCacheRepository
from app.observability.repository import OperationalRepository


logger = logging.getLogger(__name__)


def validate_startup_settings(settings: Settings) -> None:
    if not settings.internal_api_key or len(settings.internal_api_key) < 32:
        raise ValueError("INTERNAL_API_KEY is required and must be long enough")
    if not settings.allowed_domains:
        raise ValueError("ALLOWED_DOMAINS must not be empty")


def initialize_runtime(operational_repository: OperationalRepository, cache_repository: MongoCacheRepository, settings: Settings) -> None:
    try:
        operational_repository.ping()
        cache_repository.ensure_collections()
        operational_repository.ensure_collections()
        validate_startup_settings(settings)
        operational_repository.ensure_api_key("repoheal-agent", settings.internal_api_key or "")
        operational_repository.log_audit_event(
            event="startup",
            request_id=str(uuid4()),
            library=None,
            details={"service_version": settings.service_version},
        )
        curated_path = Path(__file__).resolve().parent / "registry" / "curated_registry.json"
        try:
            with open(curated_path, "r", encoding="utf-8") as handle:
                curated_registry = json.load(handle)
        except Exception:
            curated_registry = {}

        upsert_library_record = getattr(cache_repository, "upsert_library_record", None)
        if callable(upsert_library_record):
            for library, entry in curated_registry.items():
                upsert_library_record(
                    library,
                    {
                        "official_docs": entry.get("official_docs"),
                        "github_repo": entry.get("github"),
                        "verified": True,
                        "verification_source": "curated",
                    },
                )
    except Exception as exc:
        logger.exception("startup initialization failed: %s", exc)
