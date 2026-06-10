import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.db.database import get_mongo_db
from app.utils.logger import get_logger

logger = get_logger(__name__)


class CacheManager:
    """MongoDB-backed cache using a TTL collection."""

    @staticmethod
    def get(key: str) -> Optional[Any]:
        try:
            db = get_mongo_db()
            doc = db.cache.find_one({"key": key})
            if not doc:
                return None
            expires_at = doc.get("expires_at")
            if expires_at is not None:
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if expires_at <= datetime.now(timezone.utc):
                    db.cache.delete_one({"key": key})
                    return None
            return doc.get("value")
        except Exception as e:
            logger.error(f"Cache GET failed for {key}: {e}")
            return None

    @staticmethod
    def set(key: str, value: Any, ttl_seconds: int = 3600) -> bool:
        try:
            db = get_mongo_db()
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
            db.cache.update_one(
                {"key": key},
                {"$set": {
                    "key": key,
                    "value": value,
                    "expires_at": expires_at,
                    "updated_at": datetime.now(timezone.utc),
                }},
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Cache SET failed for {key}: {e}")
            return False

    @staticmethod
    def delete(key: str) -> bool:
        try:
            db = get_mongo_db()
            db.cache.delete_one({"key": key})
            return True
        except Exception as e:
            logger.error(f"Cache DELETE failed for {key}: {e}")
            return False

    @staticmethod
    def get_analysis(repo_owner: str, repo_name: str) -> Optional[Any]:
        key = f"analysis:{repo_owner}:{repo_name}"
        return CacheManager.get(key)

    @staticmethod
    def set_analysis(repo_owner: str, repo_name: str, analysis_data: Any, ttl: int = 3600) -> bool:
        key = f"analysis:{repo_owner}:{repo_name}"
        return CacheManager.set(key, analysis_data, ttl)
