from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from bson.objectid import ObjectId

from app.security import hash_api_key, is_bearer_token_valid


class InMemoryKnowledgeRepository:
    def __init__(self) -> None:
        self._symbols: dict[str, dict[str, Any]] = {}
        self._relationships: dict[ObjectId, dict[str, Any]] = {}
        self._evidence: list[dict[str, Any]] = []
        self._libraries: dict[str, dict[str, Any]] = {}

    def ensure_indexes(self) -> None:
        return None

    def lookup_symbol(self, symbol_id: str) -> dict[str, Any] | None:
        return self._symbols.get(symbol_id)

    def lookup_relationships(self, symbol_id: str) -> list[dict[str, Any]]:
        return [r for r in self._relationships.values() if r["from"] == symbol_id]

    def insert_symbol(self, symbol_id: str, library: str) -> None:
        now = datetime.now(timezone.utc)
        if symbol_id not in self._symbols:
            self._symbols[symbol_id] = {
                "_id": symbol_id,
                "library": library,
                "created_at": now,
            }

    def insert_relationship(self, from_sym: str, relation: str, to_sym: str, confidence: float, library: str) -> ObjectId:
        now = datetime.now(timezone.utc)
        # find existing
        for rel_id, rel in self._relationships.items():
            if rel["from"] == from_sym and rel["relation"] == relation and rel["to"] == to_sym:
                rel["updated_at"] = now
                return rel_id
        
        new_id = ObjectId()
        self._relationships[new_id] = {
            "_id": new_id,
            "from": from_sym,
            "relation": relation,
            "to": to_sym,
            "confidence": confidence,
            "status": "candidate",
            "library": library,
            "created_at": now,
            "updated_at": now,
        }
        return new_id

    def promote_to_verified(self, relationship_id: ObjectId) -> None:
        if relationship_id in self._relationships:
            self._relationships[relationship_id]["status"] = "verified"
            self._relationships[relationship_id]["updated_at"] = datetime.now(timezone.utc)

    def insert_evidence(self, relationship_id: ObjectId, url: str, source_type: str, snippet: str) -> None:
        # Check duplicate
        for ev in self._evidence:
            if ev["relationship_id"] == relationship_id and ev["url"] == url and ev["snippet"] == snippet:
                return
                
        now = datetime.now(timezone.utc)
        self._evidence.append({
            "relationship_id": relationship_id,
            "url": url,
            "source_type": source_type,
            "snippet": snippet,
            "retrieved_at": now,
        })

    def lookup_evidence(self, relationship_id: ObjectId) -> list[dict[str, Any]]:
        return [ev for ev in self._evidence if ev["relationship_id"] == relationship_id]

    def lookup_library(self, library: str) -> dict[str, Any] | None:
        return self._libraries.get(library)

    def upsert_library(
        self,
        library: str,
        latest_version: str | None = None,
        official_docs: str | None = None,
        github_repo: str | None = None,
        pypi_url: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        if library not in self._libraries:
            self._libraries[library] = {
                "library": library,
                "created_at": now,
                "updated_at": now,
            }
        else:
            self._libraries[library]["updated_at"] = now
            
        if latest_version is not None: self._libraries[library]["latest_version"] = latest_version
        if official_docs is not None: self._libraries[library]["official_docs"] = official_docs
        if github_repo is not None: self._libraries[library]["github_repo"] = github_repo
        if pypi_url is not None: self._libraries[library]["pypi_url"] = pypi_url


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
