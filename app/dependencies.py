from __future__ import annotations

from functools import lru_cache

import certifi
from pymongo import MongoClient

from app.cache.repository import MongoCacheRepository
from app.config import get_settings
from app.observability.repository import OperationalRepository
from app.runtime_backends import InMemoryCacheRepository, InMemoryOperationalRepository
from app.services.library_intelligence import LibraryIntelligenceService
from app.services.source_resolver import OfficialSourceResolver


@lru_cache(maxsize=1)
def get_mongo_client() -> MongoClient:
    return MongoClient(
        get_settings().mongodb_uri,
        tls=True,
        tlsCAFile=certifi.where(),
        connectTimeoutMS=10000,
        serverSelectionTimeoutMS=10000,
        socketTimeoutMS=10000,
        retryWrites=True,
        retryReads=True,
    )


def reset_mongo_dependencies() -> None:
    get_mongo_client.cache_clear()
    get_runtime_repositories.cache_clear()
    get_source_resolver.cache_clear()


@lru_cache(maxsize=1)
def get_runtime_repositories() -> tuple[object, object]:
    settings = get_settings()
    try:
        mongo_client = get_mongo_client()
        operational_repository = OperationalRepository(mongo_client, settings.mongodb_database)
        cache_repository = MongoCacheRepository(mongo_client, settings.mongodb_database, settings.cache_expiry_days)
        cache_repository.ensure_collections()
        operational_repository.ensure_collections()
        operational_repository.mark_service_status("__backend_probe__", "ok")
        return cache_repository, operational_repository
    except Exception:
        return InMemoryCacheRepository(settings.cache_expiry_days), InMemoryOperationalRepository(settings.internal_api_key)


def get_cache_repository() -> MongoCacheRepository:
    return get_runtime_repositories()[0]


def get_operational_repository() -> OperationalRepository:
    return get_runtime_repositories()[1]


@lru_cache(maxsize=1)
def get_source_resolver() -> OfficialSourceResolver:
    return OfficialSourceResolver(get_operational_repository())


def get_library_intelligence_service() -> LibraryIntelligenceService:
    return LibraryIntelligenceService(get_cache_repository(), get_operational_repository(), get_source_resolver())
