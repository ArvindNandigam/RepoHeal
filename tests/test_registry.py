from __future__ import annotations

from app.runtime_backends import InMemoryCacheRepository
from app.services.registry_service import RegistryService


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
