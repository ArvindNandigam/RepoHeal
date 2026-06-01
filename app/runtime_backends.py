from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from packaging.version import InvalidVersion, Version

from app.security import hash_api_key, is_bearer_token_valid
from app.cache.repository import CACHE_PAYLOAD_SCHEMA_VERSION


class InMemoryCacheRepository:
    def __init__(self, cache_expiry_days: int) -> None:
        self.cache_expiry = timedelta(days=cache_expiry_days)
        self.library_cache: dict[str, dict[str, Any]] = {}
        self.symbol_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self.source_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self.library_registry: dict[str, dict[str, Any]] = {}
        self.versioned_symbol_registry: dict[tuple[str, str], dict[str, Any]] = {}

    def ensure_collections(self) -> None:
        return None

    def _is_fresh(self, last_updated: datetime | None) -> bool:
        if last_updated is None:
            return False
        if last_updated.tzinfo is None:
            last_updated = last_updated.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - last_updated <= self.cache_expiry

    def _cache_key(self, library: str, symbols: list[str]) -> str:
        symbol_key = ",".join(sorted(symbols))
        return f"{library}|{symbol_key}"

    def _version_sort_key(self, value: str) -> tuple[int, Any]:
        try:
            return (0, Version(value))
        except InvalidVersion:
            return (1, value)

    def get_versioned_symbol_registry_entries(self, library: str) -> list[dict[str, Any]]:
        return [entry for (entry_library, _version), entry in self.versioned_symbol_registry.items() if entry_library == library]

    def lookup_versioned_symbol_registry(self, library: str, symbol: str) -> dict[str, Any] | None:
        entries = self.get_versioned_symbol_registry_entries(library)
        if not entries:
            return None

        versions = sorted({str(entry.get("version")) for entry in entries if str(entry.get("version") or "").strip()}, key=self._version_sort_key)
        present_versions = sorted({str(entry.get("version")) for entry in entries if symbol in (entry.get("symbols") or []) and str(entry.get("version") or "").strip()}, key=self._version_sort_key)
        absent_versions = [version for version in versions if version not in present_versions]

        return {
            "library": library,
            "symbol": symbol,
            "present_versions": present_versions,
            "absent_versions": absent_versions,
            "latest_version": versions[-1] if versions else None,
            "source": "registry",
        }

    def upsert_versioned_symbol_registry(self, library: str, version: str, symbols: list[str], indexed_at: datetime | None = None, source: str = "discovery") -> None:
        now = indexed_at or datetime.now(timezone.utc)
        self.versioned_symbol_registry[(library, version)] = {
            "library": library,
            "version": version,
            "symbols": sorted({symbol for symbol in symbols if symbol}),
            "indexed_at": now,
            "source": source,
        }

    def get_library_payload(self, library: str, symbols: list[str]) -> dict[str, Any] | None:
        record = self.library_cache.get(self._cache_key(library, symbols))
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
        self.library_cache[self._cache_key(library, symbols)] = {
            "library": library,
            "cache_key": self._cache_key(library, symbols),
            "symbols": sorted(symbols),
            "latest_version": payload["latest_version"],
            "payload_schema_version": CACHE_PAYLOAD_SCHEMA_VERSION,
            "payload": payload,
            "last_updated": now,
            "expires_at": now + self.cache_expiry,
        }

    def upsert_source_payload(self, library: str, source_type: str, payload: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        self.source_cache[(library, source_type)] = {
            "library": library,
            "source_type": source_type,
            "payload": payload,
            "last_updated": now,
            "expires_at": now + self.cache_expiry,
        }

    def upsert_permanent_source_payload(self, library: str, source_type: str, payload: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        self.source_cache[(library, source_type)] = {
            "library": library,
            "source_type": source_type,
            "payload": payload,
            "last_updated": now,
            "permanent": True,
        }

    def upsert_symbol_payload(self, library: str, symbol: str, payload: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        self.symbol_cache[(library, symbol)] = {
            "library": library,
            "symbol": symbol,
            "payload_schema_version": CACHE_PAYLOAD_SCHEMA_VERSION,
            "versions_observed": payload.get("versions_observed", []),
            "earliest_version_found": payload.get("earliest_version_found"),
            "latest_version_found": payload.get("latest_version_found"),
            "evidence": payload.get("evidence", []),
            "evidence_sources": payload.get("evidence_sources", {}),
            "migration_documents": payload.get("migration_documents", []),
            "payload": payload,
            "last_updated": now,
            "expires_at": now + self.cache_expiry,
        }

    def get_symbol_payload(self, library: str, symbol: str) -> dict[str, Any] | None:
        record = self.symbol_cache.get((library, symbol))
        if not record:
            return None
        if record.get("payload_schema_version") != CACHE_PAYLOAD_SCHEMA_VERSION:
            return None
        if not self._is_fresh(record.get("last_updated")):
            return None
        payload = record.get("payload")
        return payload if isinstance(payload, dict) else None

    def get_library_record(self, library: str) -> dict[str, Any] | None:
        record = self.library_registry.get(library)
        return dict(record) if record else None

    def upsert_library_record(self, library: str, record: dict[str, Any]) -> None:
        record_copy = dict(record)
        record_copy["library"] = library
        record_copy.setdefault("last_verified", datetime.now(timezone.utc).isoformat())
        self.library_registry[library] = record_copy


class InMemoryOperationalRepository:
    is_mongo_connected = False

    def __init__(self, internal_api_key: str | None) -> None:
        self._internal_api_key = internal_api_key or ""
        self._api_key_hashes = [hash_api_key(self._internal_api_key)] if self._internal_api_key else []
        self._service_status: dict[str, dict[str, Any]] = {}

    def ping(self) -> bool:
        return False

    def ensure_collections(self) -> None:
        return None

    def ensure_api_key(self, name: str, raw_key: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        key_hash = hash_api_key(raw_key)
        if key_hash not in self._api_key_hashes:
            self._api_key_hashes.append(key_hash)
        return {"name": name, "key_hash": key_hash, "active": True, "created_at": now}

    def get_active_api_key_hashes(self) -> list[str]:
        return list(self._api_key_hashes)

    def find_matching_api_key(self, raw_token: str) -> tuple[bool, str | None, str]:
        token_hash = hash_api_key(raw_token)
        if is_bearer_token_valid(raw_token, self._api_key_hashes):
            return True, "repoheal-agent", token_hash
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
        return None

    def log_error(self, request_id: str, endpoint: str, error_type: str, error_message: str) -> None:
        return None

    def log_audit_event(
        self,
        event: str,
        request_id: str,
        library: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        return None

    def update_daily_metrics(self, cache_hit: bool | None = None, error: bool = False) -> None:
        return None

    def get_service_status(self, service: str) -> dict[str, Any] | None:
        return self._service_status.get(service)

    def mark_service_status(self, service: str, status: str, retry_after: datetime | None = None) -> None:
        self._service_status[service] = {
            "service": service,
            "status": status,
            "retry_after": retry_after,
            "updated_at": datetime.now(timezone.utc),
        }
