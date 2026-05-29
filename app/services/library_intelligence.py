from __future__ import annotations

from typing import Any

from app.cache.repository import MongoCacheRepository
from app.observability.repository import OperationalRepository
from app.services.source_resolver import OfficialSourceResolver


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
        source_contract, symbol_lifecycles, release_history, migration_guides, _ = self.source_resolver.resolve(library, symbols)

        return {
            "library": source_contract.library,
            "latest_version": source_contract.latest_version,
            "official_docs": source_contract.official_docs,
            "github_repo": source_contract.github_repo,
            "pypi_url": source_contract.pypi_url,
            "symbol_lifecycles": [symbol_lifecycle.model_dump(mode="json") for symbol_lifecycle in symbol_lifecycles],
            "release_history": [release.model_dump(mode="json") for release in release_history],
            "migration_guides": [guide.model_dump(mode="json") for guide in migration_guides],
        }

    def resolve(self, library: str, symbols: list[str]) -> dict[str, Any]:
        response_payload = self.build_response_payload(library, symbols)
        self.cache_repository.upsert_library_payload(library, symbols, response_payload)
        self.cache_repository.upsert_source_payload(library, "pypi_json", {"latest_version": response_payload["latest_version"]})
        for symbol_lifecycle in response_payload["symbol_lifecycles"]:
            self.cache_repository.upsert_symbol_payload(library, symbol_lifecycle["symbol"], symbol_lifecycle)
        return response_payload

    def resolve_symbol(self, library: str, symbol: str) -> dict[str, Any]:
        result = self.resolve(library, [symbol])
        for lifecycle in result["symbol_lifecycles"]:
            if lifecycle["symbol"] == symbol:
                return lifecycle
        raise ValueError("symbol lifecycle not found")
