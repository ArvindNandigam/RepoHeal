from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database


CACHE_PAYLOAD_SCHEMA_VERSION = 4


class MongoCacheRepository:
    def __init__(self, mongo_client: MongoClient, database_name: str, cache_expiry_days: int) -> None:
        self.mongo_client = mongo_client
        self.database: Database = mongo_client[database_name]
        self.cache_expiry = timedelta(days=cache_expiry_days)

    @property
    def library_cache(self) -> Collection:
        return self.database["library_cache"]

    @property
    def library_registry(self) -> Collection:
        return self.database["library_registry"]

    @property
    def symbol_cache(self) -> Collection:
        return self.database["symbol_cache"]

    @property
    def source_cache(self) -> Collection:
        return self.database["source_cache"]

    @property
    def jobs(self) -> Collection:
        return self.database["jobs"]

    def ensure_collections(self) -> None:
        existing = set(self.database.list_collection_names())
        for name in ("library_cache", "symbol_cache", "source_cache", "jobs"):
            if name not in existing:
                self.database.create_collection(name)
        if "library_registry" not in existing:
            self.database.create_collection("library_registry")

        self.library_cache.create_index("cache_key", unique=True)
        self.library_cache.create_index("library")
        self.library_cache.create_index("expires_at", expireAfterSeconds=0)
        self.symbol_cache.create_index([("library", 1), ("symbol", 1)], unique=True)
        self.symbol_cache.create_index("expires_at", expireAfterSeconds=0)
        self.source_cache.create_index([("library", 1), ("source_type", 1)], unique=True)
        self.source_cache.create_index("expires_at", expireAfterSeconds=0)
        self.library_registry.create_index("library", unique=True)
        self.jobs.create_index("created_at")

    def _is_fresh(self, last_updated: datetime | None) -> bool:
        if last_updated is None:
            return False
        if last_updated.tzinfo is None:
            last_updated = last_updated.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - last_updated <= self.cache_expiry

    def _cache_key(self, library: str, symbols: list[str]) -> str:
        symbol_key = ",".join(sorted(symbols))
        return f"{library}|{symbol_key}"

    def get_library_payload(self, library: str, symbols: list[str]) -> dict[str, Any] | None:
        record = self.library_cache.find_one({"cache_key": self._cache_key(library, symbols)})
        if not record:
            return None

        if record.get("payload_schema_version") != CACHE_PAYLOAD_SCHEMA_VERSION:
            return None

        if not self._is_fresh(record.get("last_updated")):
            return None

        payload = record.get("payload")
        return payload if isinstance(payload, dict) else None

    def upsert_library_payload(self, library: str, symbols: list[str], payload: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        self.library_cache.update_one(
            {"cache_key": self._cache_key(library, symbols)},
            {
                "$set": {
                    "library": library,
                    "cache_key": self._cache_key(library, symbols),
                    "symbols": sorted(symbols),
                    "latest_version": payload["latest_version"],
                    "payload_schema_version": CACHE_PAYLOAD_SCHEMA_VERSION,
                    "payload": payload,
                    "last_updated": now,
                    "expires_at": now + self.cache_expiry,
                }
            },
            upsert=True,
        )

    def upsert_source_payload(self, library: str, source_type: str, payload: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        self.source_cache.update_one(
            {"library": library, "source_type": source_type},
            {
                "$set": {
                    "library": library,
                    "source_type": source_type,
                    "payload": payload,
                    "last_updated": now,
                    "expires_at": now + self.cache_expiry,
                }
            },
            upsert=True,
        )

    def upsert_permanent_source_payload(self, library: str, source_type: str, payload: dict[str, Any]) -> None:
        """Persist a verified source payload permanently (no expiry)."""
        now = datetime.now(timezone.utc)
        # Do not set an expires_at so TTL index won't remove this document.
        self.source_cache.update_one(
            {"library": library, "source_type": source_type},
            {
                "$set": {
                    "library": library,
                    "source_type": source_type,
                    "payload": payload,
                    "last_updated": now,
                    "permanent": True,
                }
            },
            upsert=True,
        )

    def upsert_symbol_payload(self, library: str, symbol: str, payload: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        self.symbol_cache.update_one(
            {"library": library, "symbol": symbol},
            {
                "$set": {
                    "library": library,
                    "symbol": symbol,
                    "payload_schema_version": CACHE_PAYLOAD_SCHEMA_VERSION,
                    "evidence": payload.get("evidence", []),
                    "payload": payload,
                    "last_updated": now,
                    "expires_at": now + self.cache_expiry,
                }
            },
            upsert=True,
        )

    def get_symbol_payload(self, library: str, symbol: str) -> dict[str, Any] | None:
        record = self.symbol_cache.find_one({"library": library, "symbol": symbol})
        if not record:
            return None

        if record.get("payload_schema_version") != CACHE_PAYLOAD_SCHEMA_VERSION:
            return None

        if not self._is_fresh(record.get("last_updated")):
            return None

        payload = record.get("payload")
        return payload if isinstance(payload, dict) else None

    def get_library_record(self, library: str) -> dict[str, Any] | None:
        record = self.library_registry.find_one({"library": library})
        return record if record else None

    def upsert_library_record(self, library: str, record: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        record_copy = dict(record)
        record_copy["library"] = library
        record_copy.setdefault("last_verified", now.isoformat())
        self.library_registry.update_one({"library": library}, {"$set": record_copy}, upsert=True)
