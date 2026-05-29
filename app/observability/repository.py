from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from app.contracts.schemas import ApiKeyContract, AuditLogContract, ErrorLogContract, RequestLogContract, ServiceMetricsContract
from app.security import hash_api_key, is_bearer_token_valid


class OperationalRepository:
    def __init__(self, mongo_client: MongoClient, database_name: str) -> None:
        self.mongo_client = mongo_client
        self.database: Database = mongo_client[database_name]

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

    def ensure_collections(self) -> None:
        existing = set(self.database.list_collection_names())
        for name in (
            "request_logs",
            "error_logs",
            "service_metrics",
            "api_keys",
            "audit_logs",
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

    def ping(self) -> bool:
        self.database.command("ping")
        return True

    def ensure_api_key(self, name: str, raw_key: str) -> ApiKeyContract:
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
        return ApiKeyContract(name=name, key_hash=key_hash, active=True, created_at=now)

    def get_active_api_key_hashes(self) -> list[str]:
        return [record["key_hash"] for record in self.api_keys.find({"active": True}, {"_id": 0, "key_hash": 1})]

    def find_matching_api_key(self, raw_token: str) -> tuple[bool, str | None, str]:
        token_hash = hash_api_key(raw_token)
        for record in self.api_keys.find({"active": True}, {"_id": 0, "name": 1, "key_hash": 1}):
            if is_bearer_token_valid(raw_token, [record["key_hash"]]):
                return True, record.get("name"), token_hash
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
        payload = RequestLogContract(
            request_id=request_id,
            endpoint=endpoint,
            library=library,
            libraries=libraries,
            symbols=symbols,
            cache_hit=cache_hit,
            response_time_ms=response_time_ms,
            status=status,
            timestamp=datetime.now(timezone.utc),
        )
        self.request_logs.insert_one(payload.model_dump())

    def log_error(self, request_id: str, endpoint: str, error_type: str, error_message: str) -> None:
        payload = ErrorLogContract(
            request_id=request_id,
            endpoint=endpoint,
            error_type=error_type,
            error_message=error_message,
            timestamp=datetime.now(timezone.utc),
        )
        self.error_logs.insert_one(payload.model_dump())

    def log_audit_event(
        self,
        event: str,
        request_id: str,
        library: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        payload = AuditLogContract(
            event=event,
            request_id=request_id,
            library=library,
            details=details,
            timestamp=datetime.now(timezone.utc),
        )
        self.audit_logs.insert_one(payload.model_dump())

    def update_daily_metrics(self, cache_hit: bool | None = None, error: bool = False) -> None:
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
