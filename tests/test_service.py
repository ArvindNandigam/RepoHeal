from __future__ import annotations

from types import SimpleNamespace

from app import dependencies
from app.contracts.schemas import MigrationGuideContract, ReleaseArtifactContract, SourceContract
from app.services.library_intelligence import LibraryIntelligenceService


class DummyRepository:
    def __init__(self) -> None:
        self.cached: dict[str, dict] = {}
        self.saved: list[tuple[str, str, dict]] = []

    def get_library_payload(self, library: str, symbols: list[str]):
        return self.cached.get((library, tuple(sorted(symbols))))

    def upsert_library_payload(self, library: str, symbols: list[str], payload: dict) -> None:
        self.cached[(library, tuple(sorted(symbols)))] = payload

    def upsert_source_payload(self, library: str, source_type: str, payload: dict) -> None:
        self.saved.append((library, source_type, payload))

    def upsert_symbol_payload(self, library: str, symbol: str, payload: dict) -> None:
        self.saved.append((library, symbol, payload))


class DummyResolver:
    def resolve(self, library: str, symbols: list[str]):
        source_contract = SourceContract.model_validate(
            {
                "library": library,
                "official_docs": "https://docs.openai.com/",
                "github_repo": "https://github.com/openai/openai-python",
                "pypi_url": "https://pypi.org/pypi/openai/json",
                "latest_version": "1.52.0",
            }
        )
        release_history = [ReleaseArtifactContract(version="1.52.0", url="https://github.com/openai/openai-python/releases/tag/v1.52.0")]
        migration_guides = [MigrationGuideContract(title="Migration Guide", url="https://docs.openai.com/migration")]
        symbol_lifecycles = [SimpleNamespace(symbol=symbols[0], model_dump=lambda mode="json": {"symbol": symbols[0], "introduced_version": "0.0.0", "deprecated_version": None, "removed_version": None, "replacement_symbol": None})] if symbols else []
        return source_contract, symbol_lifecycles, release_history, migration_guides, {}


class DummyOperationalRepository:
    def get_service_status(self, service: str):
        return None

    def mark_service_status(self, service: str, status: str, retry_after=None) -> None:
        return None


def test_service_uses_cache_when_present() -> None:
    repository = DummyRepository()
    repository.cached[("openai", ("openai.ChatCompletion.create",))] = {
        "library": "openai",
        "latest_version": "1.52.0",
        "official_docs": "https://docs.openai.com/",
        "github_repo": "https://github.com/openai/openai-python",
        "pypi_url": "https://pypi.org/pypi/openai/json",
        "symbol_lifecycles": [],
        "release_history": [],
        "migration_guides": [],
    }
    service = LibraryIntelligenceService(repository, DummyOperationalRepository(), DummyResolver())

    response = service.resolve("openai", ["openai.ChatCompletion.create"])

    assert response.library == "openai"
    assert response.latest_version == "1.52.0"


def test_reset_mongo_dependencies_clears_cached_singletons(monkeypatch) -> None:
    cleared: list[str] = []

    monkeypatch.setattr(dependencies.get_mongo_client, "cache_clear", lambda: cleared.append("get_mongo_client"))
    monkeypatch.setattr(dependencies.get_cache_repository, "cache_clear", lambda: cleared.append("get_cache_repository"))
    monkeypatch.setattr(dependencies.get_operational_repository, "cache_clear", lambda: cleared.append("get_operational_repository"))
    monkeypatch.setattr(dependencies.get_source_resolver, "cache_clear", lambda: cleared.append("get_source_resolver"))

    dependencies.reset_mongo_dependencies()

    assert cleared == ["get_mongo_client", "get_cache_repository", "get_operational_repository", "get_source_resolver"]

