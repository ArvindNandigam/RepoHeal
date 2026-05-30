from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from app.contracts.schemas import SourceContract, ToolResponseContract


@lru_cache(maxsize=1)
def _load_curated_registry() -> dict[str, dict[str, str]]:
    path = Path(__file__).resolve().parents[1] / "registry" / "curated_registry.json"
    try:
        import json

        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


class RegistryService:
    def __init__(self, cache_repository: Any, source_resolver: Any) -> None:
        self.cache_repository = cache_repository
        self.source_resolver = source_resolver
        self.curated = _load_curated_registry()

    def get_library_metadata(self, library: str, symbols: list[str]) -> dict[str, Any]:
        # 1) cache
        cached = self.cache_repository.get_library_payload(library, symbols)
        if cached is not None:
            return cached

        # 2) curated registry
        curated_entry = self.curated.get(library)
        if curated_entry:
            # Use resolver to fetch full details (release history, symbol lifecycles)
            source_contract, symbol_lifecycles, release_history, migration_guides, pypi_json = self.source_resolver.resolve(library, symbols)

            result = {
                "library": source_contract.library,
                "latest_version": source_contract.latest_version,
                "official_docs": curated_entry.get("official_docs") or source_contract.official_docs,
                "github_repo": curated_entry.get("github") or source_contract.github_repo,
                "pypi_url": source_contract.pypi_url,
                "symbol_lifecycles": [s.model_dump(mode="json") for s in symbol_lifecycles],
                "release_history": [r.model_dump(mode="json") for r in release_history],
                "migration_guides": [g.model_dump(mode="json") for g in migration_guides],
            }

            # persist permanent source metadata (curated)
            try:
                self.cache_repository.upsert_permanent_source_payload(library, "curated", {"official_docs": result["official_docs"], "github_repo": result["github_repo"]})
            except Exception:
                pass

            return result

        # 3) fallback to resolver discovery
        source_contract, symbol_lifecycles, release_history, migration_guides, pypi_json = self.source_resolver.resolve(library, symbols)
        result = {
            "library": source_contract.library,
            "latest_version": source_contract.latest_version,
            "official_docs": source_contract.official_docs,
            "github_repo": source_contract.github_repo,
            "pypi_url": source_contract.pypi_url,
            "symbol_lifecycles": [s.model_dump(mode="json") for s in symbol_lifecycles],
            "release_history": [r.model_dump(mode="json") for r in release_history],
            "migration_guides": [g.model_dump(mode="json") for g in migration_guides],
        }

        # do not persist discovered sources as permanent automatically
        try:
            self.cache_repository.upsert_source_payload(library, "pypi_json", {"latest_version": result["latest_version"]})
        except Exception:
            pass

        return result
