from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import PyMongoError

from app.security import hash_api_key, is_bearer_token_valid


logger = logging.getLogger(__name__)


class OperationalRepository:
    _mongo_disabled_until: datetime | None = None

    def __init__(self, mongo_client: MongoClient, database_name: str) -> None:
        self.mongo_client = mongo_client
        self.database: Database = mongo_client[database_name]

    @classmethod
    def _is_mongo_temporarily_disabled(cls) -> bool:
        if cls._mongo_disabled_until is None:
            return False
        return datetime.now(timezone.utc) < cls._mongo_disabled_until

    @classmethod
    def _disable_mongo_temporarily(cls, minutes: int = 10) -> None:
        cls._mongo_disabled_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)

    @classmethod
    def _clear_mongo_disable(cls) -> None:
        cls._mongo_disabled_until = None

    @classmethod
    def _reset_mongo_state(cls) -> None:
        from app.dependencies import reset_mongo_dependencies

        cls._disable_mongo_temporarily()
        reset_mongo_dependencies()

    @classmethod
    def _handle_mongo_failure(cls, exc: Exception, message: str, *args: Any) -> None:
        logger.warning(message, *args, exc_info=True)
        if isinstance(exc, PyMongoError):
            cls._reset_mongo_state()
        else:
            cls._disable_mongo_temporarily()

    @property
    def request_logs(self) -> Collection:
        return self.database["request_logs"]

    @property
    def error_logs(self) -> Collection:
        return self.database["error_logs"]

    @property
    def service_metrics(self) -> Collection:
        return self.database["service_metrics"]

    @property
    def api_keys(self) -> Collection:
        return self.database["api_keys"]

    @property
    def audit_logs(self) -> Collection:
        return self.database["audit_logs"]

    @property
    def service_status(self) -> Collection:
        return self.database["service_status"]

    def ensure_collections(self) -> None:
        existing = set(self.database.list_collection_names())
        for name in (
            "request_logs",
            "error_logs",
            "service_metrics",
            "api_keys",
            "audit_logs",
            "service_status",
        ):
            if name not in existing:
                self.database.create_collection(name)

        self.request_logs.create_index("request_id", unique=True)
        self.request_logs.create_index("endpoint")
        self.request_logs.create_index("library")
        self.request_logs.create_index("timestamp", expireAfterSeconds=60 * 60 * 24 * 30)

        self.error_logs.create_index("request_id")
        self.error_logs.create_index("error_type")
        self.error_logs.create_index("timestamp", expireAfterSeconds=60 * 60 * 24 * 90)

        self.service_metrics.create_index("date", unique=True)

        self.api_keys.create_index("name", unique=True)
        self.api_keys.create_index("active")

        self.audit_logs.create_index("event")
        self.audit_logs.create_index("timestamp")
        self.audit_logs.create_index("library")

        self.service_status.create_index("service", unique=True)
        self.service_status.create_index("status")
        self.service_status.create_index("retry_after")

    def ping(self) -> bool:
        if self._is_mongo_temporarily_disabled():
            raise RuntimeError("mongodb temporarily disabled")
        self.database.command("ping")
        self._clear_mongo_disable()
        return True

    def ensure_api_key(self, name: str, raw_key: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        key_hash = hash_api_key(raw_key)
        self.api_keys.update_one(
            {"name": name},
            {
                "$set": {
                    "name": name,
                    "key_hash": key_hash,
                    "active": True,
                },
                "$setOnInsert": {
                    "created_at": now,
                },
            },
            upsert=True,
        )
        return {"name": name, "key_hash": key_hash, "active": True, "created_at": now}

    def get_active_api_key_hashes(self) -> list[str]:
        if self._is_mongo_temporarily_disabled():
            return []
        try:
            return [record["key_hash"] for record in self.api_keys.find({"active": True}, {"_id": 0, "key_hash": 1})]
        except Exception as exc:
            self._handle_mongo_failure(exc, "failed to read active api key hashes: %s")
            return []

    def find_matching_api_key(self, raw_token: str) -> tuple[bool, str | None, str]:
        token_hash = hash_api_key(raw_token)
        if self._is_mongo_temporarily_disabled():
            return False, None, token_hash
        try:
            for record in self.api_keys.find({"active": True}, {"_id": 0, "name": 1, "key_hash": 1}):
                if is_bearer_token_valid(raw_token, [record["key_hash"]]):
                    return True, record.get("name"), token_hash
        except Exception as exc:
            self._handle_mongo_failure(exc, "failed to validate api key: %s")
        return False, None, token_hash

    def log_request(
        self,
        request_id: str,
        endpoint: str,
        library: str | None,
        symbols: list[str] | None,
        cache_hit: bool,
        response_time_ms: int,
        status: str,
        libraries: list[str] | None = None,
    ) -> None:
        if self._is_mongo_temporarily_disabled():
            return
        try:
            payload = {
                "request_id": request_id,
                "endpoint": endpoint,
                "library": library,
                "libraries": libraries,
                "symbols": symbols,
                "cache_hit": cache_hit,
                "response_time_ms": response_time_ms,
                "status": status,
                "timestamp": datetime.now(timezone.utc),
            }
            self.request_logs.insert_one(payload)
        except Exception as exc:
            self._handle_mongo_failure(exc, "failed to write request log: %s")

    def log_error(self, request_id: str, endpoint: str, error_type: str, error_message: str) -> None:
        if self._is_mongo_temporarily_disabled():
            return
        try:
            payload = {
                "request_id": request_id,
                "endpoint": endpoint,
                "error_type": error_type,
                "error_message": error_message,
                "timestamp": datetime.now(timezone.utc),
            }
            self.error_logs.insert_one(payload)
        except Exception as exc:
            self._handle_mongo_failure(exc, "failed to write error log: %s")

    def log_audit_event(
        self,
        event: str,
        request_id: str,
        library: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        if self._is_mongo_temporarily_disabled():
            return
        try:
            payload = {
                "event": event,
                "request_id": request_id,
                "library": library,
                "details": details,
                "timestamp": datetime.now(timezone.utc),
            }
            self.audit_logs.insert_one(payload)
        except Exception as exc:
            self._handle_mongo_failure(exc, "failed to write audit log: %s")

    def update_daily_metrics(self, cache_hit: bool | None = None, error: bool = False) -> None:
        if self._is_mongo_temporarily_disabled():
            return
        try:
            now = datetime.now(timezone.utc)
            metrics = {"requests": 1}
            if cache_hit is True:
                metrics["cache_hits"] = 1
            elif cache_hit is False:
                metrics["cache_misses"] = 1
            if error:
                metrics["errors"] = 1

            self.service_metrics.update_one(
                {"date": now.date().isoformat()},
                {
                    "$setOnInsert": {"date": now.date().isoformat()},
                    "$set": {"updated_at": now},
                    "$inc": metrics,
                },
                upsert=True,
            )
        except Exception as exc:
            self._handle_mongo_failure(exc, "failed to update metrics: %s")

    def get_service_status(self, service: str) -> dict[str, Any] | None:
        if self._is_mongo_temporarily_disabled():
            return None
        try:
            return self.service_status.find_one({"service": service}, {"_id": 0})
        except Exception as exc:
            self._handle_mongo_failure(exc, "failed to read service status for %s: %s", service, exc)
            return None

    def mark_service_status(self, service: str, status: str, retry_after: datetime | None = None) -> None:
        if self._is_mongo_temporarily_disabled():
            return
        try:
            payload: dict[str, Any] = {
                "service": service,
                "status": status,
                "retry_after": retry_after,
                "updated_at": datetime.now(timezone.utc),
            }
            self.service_status.update_one({"service": service}, {"$set": payload}, upsert=True)
        except Exception as exc:
            self._handle_mongo_failure(exc, "failed to write service status for %s: %s", service, exc)
