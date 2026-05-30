from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any


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
            source_contract, symbol_lifecycles, release_history, migration_guides, pypi_json = self.source_resolver.resolve(library, symbols, trust_sources=True)

            result = {
                "library": source_contract["library"],
                "latest_version": source_contract["latest_version"],
                "official_docs": curated_entry.get("official_docs") or source_contract["official_docs"],
                "github_repo": curated_entry.get("github") or source_contract["github_repo"],
                "pypi_url": source_contract["pypi_url"],
                "symbol_lifecycles": symbol_lifecycles,
                "release_history": release_history,
                "migration_guides": migration_guides,
            }

            # persist permanent source metadata (curated)
            try:
                # Persist curated entry into library_registry as verified
                self.cache_repository.upsert_library_record(library, {
                    "official_docs": result["official_docs"],
                    "github_repo": result["github_repo"],
                    "verified": True,
                    "verification_source": "curated",
                })
                # also persist permanent source payload
                try:
                    self.cache_repository.upsert_permanent_source_payload(library, "curated", {"official_docs": result["official_docs"], "github_repo": result["github_repo"]})
                except Exception:
                    pass
            except Exception:
                pass

            return result

        # 3) check library_registry in DB (previously verified)
        record = None
        try:
            record = self.cache_repository.get_library_record(library)
        except Exception:
            record = None

        if record and record.get("verified"):
            # trusted record exists; fetch latest symbol lifecycles but skip URL validation
            source_contract, symbol_lifecycles, release_history, migration_guides, pypi_json = self.source_resolver.resolve(library, symbols, trust_sources=True)
            result = {
                "library": record.get("library", library),
                "latest_version": source_contract["latest_version"],
                "official_docs": record.get("official_docs") or source_contract["official_docs"],
                "github_repo": record.get("github_repo") or source_contract["github_repo"],
                "pypi_url": source_contract["pypi_url"],
                "symbol_lifecycles": symbol_lifecycles,
                "release_history": release_history,
                "migration_guides": migration_guides,
            }
            return result

        # 4) fallback to resolver discovery (first-time discovery + verification)
        source_contract, symbol_lifecycles, release_history, migration_guides, pypi_json = self.source_resolver.resolve(library, symbols)
        result = {
            "library": source_contract["library"],
            "latest_version": source_contract["latest_version"],
            "official_docs": source_contract["official_docs"],
            "github_repo": source_contract["github_repo"],
            "pypi_url": source_contract["pypi_url"],
            "symbol_lifecycles": symbol_lifecycles,
            "release_history": release_history,
            "migration_guides": migration_guides,
        }

        # Verify the hosts are within an allowed small whitelist before marking as verified
        allowed_hosts = ("github.com", "readthedocs.io", "readthedocs.com")
        from urllib.parse import urlparse as _urlparse

        try:
            docs_host = _urlparse(source_contract["official_docs"]).hostname or ""
            repo_host = _urlparse(source_contract["github_repo"]).hostname or ""
            docs_ok = any(docs_host == h or docs_host.endswith(f".{h}") for h in allowed_hosts)
            repo_ok = any(repo_host == h or repo_host.endswith(f".{h}") for h in allowed_hosts)
            if repo_ok or docs_ok:
                # persist verified library record
                try:
                    self.cache_repository.upsert_library_record(library, {
                        "official_docs": source_contract["official_docs"],
                        "github_repo": source_contract["github_repo"],
                        "verified": True,
                        "verification_source": "pypi",
                    })
                except Exception:
                    pass
        except Exception:
            pass

        # persist a short-lived pypi_json entry
        try:
            self.cache_repository.upsert_source_payload(library, "pypi_json", {"latest_version": result["latest_version"]})
        except Exception:
            pass

        return result
