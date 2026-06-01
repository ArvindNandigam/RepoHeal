from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from packaging.version import InvalidVersion, Version


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

    def _version_sort_key(self, value: str) -> tuple[int, Any]:
        try:
            return (0, Version(value))
        except InvalidVersion:
            return (1, value)

    def _latest_version(self, versions: list[str]) -> str | None:
        if not versions:
            return None
        return sorted(versions, key=self._version_sort_key)[-1]

    def _registry_hit_response(self, library: str, symbol_results: list[dict[str, Any]], debug: bool = False, source: str = "registry") -> dict[str, Any]:
        if len(symbol_results) == 1:
            item = dict(symbol_results[0])
            if debug:
                payload = self.cache_repository.get_symbol_payload(library, item["symbol"])
                evidence = (payload or {}).get("evidence") or []
                item["evidence"] = evidence
                item["urls"] = sorted({str(entry.get("url")) for entry in evidence if entry.get("url")})
            item["source"] = source
            return item

        response = {
            "library": library,
            "source": source,
            "symbols": [],
        }
        for item in symbol_results:
            symbol_item = dict(item)
            if debug:
                payload = self.cache_repository.get_symbol_payload(library, symbol_item["symbol"])
                evidence = (payload or {}).get("evidence") or []
                symbol_item["evidence"] = evidence
                symbol_item["urls"] = sorted({str(entry.get("url")) for entry in evidence if entry.get("url")})
            symbol_item["source"] = source
            response["symbols"].append(symbol_item)
        return response

    def _index_versioned_registry(self, library: str, release_history: list[dict[str, Any]], symbol_lifecycles: list[dict[str, Any]]) -> None:
        version_symbols: dict[str, set[str]] = {}
        for lifecycle in symbol_lifecycles:
            symbol = str(lifecycle.get("symbol") or "").strip()
            if not symbol:
                continue
            present_versions = lifecycle.get("observed_present") or lifecycle.get("versions_observed") or []
            for version in present_versions:
                version_symbols.setdefault(str(version), set()).add(symbol)

        release_versions = [str(entry.get("version")) for entry in release_history if str(entry.get("version") or "").strip()]
        indexed_versions = release_versions or list(version_symbols.keys())
        for version in indexed_versions:
            self.cache_repository.upsert_versioned_symbol_registry(library, version, sorted(version_symbols.get(version, set())), source="discovery")

    def resolve_symbol_intelligence(self, library: str, symbols: list[str], debug: bool = False) -> dict[str, Any]:
        unique_symbols = []
        seen: set[str] = set()
        for symbol in symbols:
            cleaned = symbol.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            unique_symbols.append(cleaned)

        registry_results: list[dict[str, Any]] = []
        registry_hits = True
        for symbol in unique_symbols:
            result = None
            try:
                result = self.cache_repository.lookup_versioned_symbol_registry(library, symbol)
            except Exception:
                result = None
            if result is None:
                registry_hits = False
                break
            registry_results.append(result)

        if registry_hits and registry_results:
            self.last_cache_hit = True
            return self._registry_hit_response(library, registry_results, debug=debug, source="registry")

        self.last_cache_hit = False
        source_contract, symbol_lifecycles, release_history, migration_guides, pypi_json = self.source_resolver.resolve(library, unique_symbols, trust_sources=True)
        self._index_versioned_registry(library, release_history, symbol_lifecycles)

        for symbol_lifecycle in symbol_lifecycles:
            try:
                self.cache_repository.upsert_symbol_payload(library, symbol_lifecycle["symbol"], symbol_lifecycle)
            except Exception:
                pass

        discovered_results: list[dict[str, Any]] = []
        for symbol in unique_symbols:
            snapshot = None
            try:
                snapshot = self.cache_repository.lookup_versioned_symbol_registry(library, symbol)
            except Exception:
                snapshot = None
            if snapshot is None:
                snapshot = {
                    "library": library,
                    "symbol": symbol,
                    "present_versions": [],
                    "absent_versions": [str(entry.get("version")) for entry in release_history if str(entry.get("version") or "").strip()],
                    "source": "discovery",
                }
            else:
                snapshot["source"] = "discovery"
            discovered_results.append(snapshot)

        return self._registry_hit_response(library, discovered_results, debug=debug, source="discovery")
