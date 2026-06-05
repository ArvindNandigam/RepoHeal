from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_client = None
_db = None


def get_mongo_client():
    global _client
    if _client is None:
        mongo_uri = getattr(settings, "MONGODB_URI", None)
        if not mongo_uri:
            raise ValueError("MONGODB_URI is not set")
        _client = MongoClient(mongo_uri)
    return _client


def get_mongo_db():
    global _db
    if _db is None:
        client = get_mongo_client()
        db_name = getattr(settings, "MONGODB_DATABASE", "RepoHeal")
        _db = client[db_name]
        _ensure_indexes(_db)
    return _db


def _ensure_indexes(db):
    """Create TTL and lookup indexes on first connection."""
    try:
        # Sessions: auto-expire via TTL index
        db.sessions.create_index("expires_at", expireAfterSeconds=0)
        db.sessions.create_index("session_id", unique=True)
        db.sessions.create_index("github_id")

        # Cache: auto-expire via TTL index
        db.cache.create_index("expires_at", expireAfterSeconds=0)
        db.cache.create_index("key", unique=True)

        # Jobs: lookup by job_id, auto-expire old jobs after 24h
        db.jobs.create_index("job_id", unique=True)
        db.jobs.create_index("expires_at", expireAfterSeconds=0)

        logger.info("MongoDB indexes ensured")
    except Exception as e:
        logger.warning(f"Failed to create MongoDB indexes (non-fatal): {e}")


def check_mongo_health() -> bool:
    try:
        client = get_mongo_client()
        client.admin.command("ping")
        return True
    except (ConnectionFailure, Exception):
        return False
