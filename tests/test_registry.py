from __future__ import annotations

from app.runtime_backends import InMemoryCacheRepository
from app.services.registry_service import RegistryService
from app.services.library_intelligence import LibraryIntelligenceService


class FailingResolver:
    def resolve(self, library: str, symbols: list[str], trust_sources: bool = False):
        raise AssertionError("discovery should not be called for registry hits")


class FakeResolver:
    def resolve(self, library: str, symbols: list[str], trust_sources: bool = False):
        if trust_sources:
            source = {
                "library": library,
                "official_docs": "https://example.org/docs",
                "github_repo": f"https://github.com/example/{library}",
                "pypi_url": f"https://pypi.org/pypi/{library}/json",
                "latest_version": "1.2.3",
            }
        else:
            source = {
                "library": library,
                "official_docs": f"https://{library}.org/doc",
                "github_repo": f"https://github.com/example/{library}",
                "pypi_url": f"https://pypi.org/pypi/{library}/json",
                "latest_version": "1.2.3",
            }
        lifecycles = [{"symbol": sym, "introduced_version": "1.0.0"} for sym in symbols]
        if trust_sources:
            releases = [{"version": "1.2.3", "url": source["github_repo"]}]
            guides = [{"title": "Guide", "url": source["official_docs"]}]
        else:
            releases = [{"version": "1.2.3", "url": source["github_repo"]}]
            guides = [{"title": "Guide", "url": source["official_docs"]}]
        return source, lifecycles, releases, guides, {}


def test_registry_service_curated_lookup():
    cache = InMemoryCacheRepository(cache_expiry_days=7)
    resolver = FakeResolver()
    svc = RegistryService(cache, resolver)

    # pick a curated library we added; the resolver returns an unapproved docs host,
    # but curated entries should bypass validation.
    library = "fastapi"
    result = svc.get_library_metadata(library, ["array"])

    assert result["library"] == "fastapi"
    assert "official_docs" in result and result["official_docs"]
    assert "symbol_lifecycles" in result


def test_symbol_intelligence_uses_versioned_registry_first():
    cache = InMemoryCacheRepository(cache_expiry_days=7)
    cache.upsert_versioned_symbol_registry("openai", "0.28.1", ["openai.ChatCompletion.create"])
    cache.upsert_versioned_symbol_registry("openai", "1.0.0", [])
    cache.upsert_versioned_symbol_registry("openai", "2.38.0", [])

    service = LibraryIntelligenceService(cache, object(), FailingResolver())

    response = service.resolve_symbol_intelligence("openai", ["openai.ChatCompletion.create"], debug=False)

    assert response["source"] == "registry"
    assert response["symbol"] == "openai.ChatCompletion.create"
    assert response["present_versions"] == ["0.28.1"]
    assert response["absent_versions"] == ["1.0.0", "2.38.0"]
