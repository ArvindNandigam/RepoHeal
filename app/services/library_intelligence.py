from __future__ import annotations

from typing import Any

from app.cache.repository import MongoCacheRepository
from app.observability.repository import OperationalRepository
from app.services.source_resolver import OfficialSourceResolver
from app.services.registry_service import RegistryService


class LibraryIntelligenceService:
    def __init__(self, cache_repository: MongoCacheRepository, operational_repository: OperationalRepository, source_resolver: OfficialSourceResolver) -> None:
        self.cache_repository = cache_repository
        self.operational_repository = operational_repository
        self.source_resolver = source_resolver
        self.last_cache_hit = False

    def build_response_payload(self, library: str, symbols: list[str]) -> dict[str, Any]:
        cached_payload = self.cache_repository.get_library_payload(library, symbols)
        if cached_payload is not None:
            self.last_cache_hit = True
            return cached_payload

        self.last_cache_hit = False
        registry = RegistryService(self.cache_repository, self.source_resolver)
        result = registry.get_library_metadata(library, symbols)
        return result

    def resolve(self, library: str, symbols: list[str]) -> dict[str, Any]:
        response_payload = self.build_response_payload(library, symbols)
        response_payload.setdefault("symbol_lifecycles", [])
        response_payload.setdefault("release_history", [])
        response_payload.setdefault("migration_guides", [])
        self.cache_repository.upsert_library_payload(library, symbols, response_payload)
        # If this library was curated we persisted permanent source payloads inside RegistryService.
        # Ensure a short-lived pypi_json entry is present as well for quick metadata lookups.
        try:
            self.cache_repository.upsert_source_payload(library, "pypi_json", {"latest_version": response_payload["latest_version"]})
        except Exception:
            pass

        for symbol_lifecycle in response_payload.get("symbol_lifecycles") or []:
            try:
                self.cache_repository.upsert_symbol_payload(library, symbol_lifecycle["symbol"], symbol_lifecycle)
            except Exception:
                pass
        return response_payload

    def resolve_symbol(self, library: str, symbol: str) -> dict[str, Any]:
        cached_symbol = None
        try:
            cached_symbol = self.cache_repository.get_symbol_payload(library, symbol)
        except Exception:
            cached_symbol = None

        if cached_symbol is not None:
            self.last_cache_hit = True
            return cached_symbol

        result = self.resolve(library, [symbol])
        for lifecycle in result.get("symbol_lifecycles") or []:
            if lifecycle["symbol"] == symbol:
                return lifecycle
        raise ValueError("symbol lifecycle not found")
