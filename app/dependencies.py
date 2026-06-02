from __future__ import annotations

from functools import lru_cache

import certifi
from pymongo import MongoClient

from app.knowledge.repository import KnowledgeRepository
from app.config import get_settings
from app.observability.repository import OperationalRepository
from app.runtime_backends import InMemoryKnowledgeRepository, InMemoryOperationalRepository
from app.services.migration_engine import MigrationEngine

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

@lru_cache(maxsize=1)
def get_runtime_repositories() -> tuple[object, object]:
    settings = get_settings()
    try:
        mongo_client = get_mongo_client()
        operational_repository = OperationalRepository(mongo_client, settings.mongodb_database)
        knowledge_repository = KnowledgeRepository(mongo_client, settings.mongodb_database)
        knowledge_repository.ensure_indexes()
        operational_repository.ensure_collections()
        operational_repository.mark_service_status("__backend_probe__", "ok")
        return knowledge_repository, operational_repository
    except Exception:
        return InMemoryKnowledgeRepository(), InMemoryOperationalRepository(settings.internal_api_key)

def get_knowledge_repository() -> KnowledgeRepository:
    return get_runtime_repositories()[0]

def get_operational_repository() -> OperationalRepository:
    return get_runtime_repositories()[1]

def get_migration_engine() -> MigrationEngine:
    return MigrationEngine(get_knowledge_repository())
