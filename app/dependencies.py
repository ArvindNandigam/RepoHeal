from __future__ import annotations

from functools import lru_cache

from pymongo import MongoClient

from app.cache.repository import MongoCacheRepository
from app.config import get_settings
from app.observability.repository import OperationalRepository
from app.services.library_intelligence import LibraryIntelligenceService
from app.services.source_resolver import OfficialSourceResolver


@lru_cache(maxsize=1)
def get_mongo_client() -> MongoClient:
    return MongoClient(get_settings().mongodb_uri)


@lru_cache(maxsize=1)
def get_cache_repository() -> MongoCacheRepository:
    settings = get_settings()
    return MongoCacheRepository(get_mongo_client(), settings.mongodb_database, settings.cache_expiry_days)


@lru_cache(maxsize=1)
def get_operational_repository() -> OperationalRepository:
    settings = get_settings()
    return OperationalRepository(get_mongo_client(), settings.mongodb_database)


@lru_cache(maxsize=1)
def get_source_resolver() -> OfficialSourceResolver:
    return OfficialSourceResolver()


def get_library_intelligence_service() -> LibraryIntelligenceService:
    return LibraryIntelligenceService(get_cache_repository(), get_source_resolver())
