from __future__ import annotations

from types import SimpleNamespace

from app import dependencies
from app.contracts.schemas import MigrationGuideContract, ReleaseArtifactContract, SourceContract
from app.runtime_backends import InMemoryCacheRepository, InMemoryOperationalRepository
from app.services.library_intelligence import LibraryIntelligenceService
from app.services import source_resolver


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

    assert response["library"] == "openai"
    assert response["latest_version"] == "1.52.0"


def test_reset_mongo_dependencies_clears_cached_singletons(monkeypatch) -> None:
    cleared: list[str] = []

    monkeypatch.setattr(dependencies.get_mongo_client, "cache_clear", lambda: cleared.append("get_mongo_client"))
    monkeypatch.setattr(dependencies.get_runtime_repositories, "cache_clear", lambda: cleared.append("get_runtime_repositories"))
    monkeypatch.setattr(dependencies.get_source_resolver, "cache_clear", lambda: cleared.append("get_source_resolver"))

    dependencies.reset_mongo_dependencies()

    assert cleared == ["get_mongo_client", "get_runtime_repositories", "get_source_resolver"]


def test_runtime_repositories_fall_back_to_memory_when_mongo_ping_fails(monkeypatch) -> None:
    class FailingOperationalRepository:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def ping(self) -> bool:
            raise RuntimeError("mongo unavailable")

    class DummyMongoCacheRepository:
        def __init__(self, *args, **kwargs) -> None:
            pass

    monkeypatch.setattr(dependencies, "OperationalRepository", FailingOperationalRepository)
    monkeypatch.setattr(dependencies, "MongoCacheRepository", DummyMongoCacheRepository)
    monkeypatch.setattr(dependencies, "get_mongo_client", lambda: object())
    dependencies.get_runtime_repositories.cache_clear()

    cache_repository, operational_repository = dependencies.get_runtime_repositories()

    assert isinstance(cache_repository, InMemoryCacheRepository)
    assert isinstance(operational_repository, InMemoryOperationalRepository)


def test_runtime_repositories_fall_back_to_memory_when_write_probe_fails(monkeypatch) -> None:
    class FailingOperationalRepository:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def ensure_collections(self) -> None:
            return None

        def mark_service_status(self, service: str, status: str, retry_after=None) -> None:
            raise RuntimeError("mongo write failed")

    class DummyMongoCacheRepository:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def ensure_collections(self) -> None:
            return None

    monkeypatch.setattr(dependencies, "OperationalRepository", FailingOperationalRepository)
    monkeypatch.setattr(dependencies, "MongoCacheRepository", DummyMongoCacheRepository)
    monkeypatch.setattr(dependencies, "get_mongo_client", lambda: object())
    dependencies.get_runtime_repositories.cache_clear()

    cache_repository, operational_repository = dependencies.get_runtime_repositories()

    assert isinstance(cache_repository, InMemoryCacheRepository)
    assert isinstance(operational_repository, InMemoryOperationalRepository)


def test_source_resolver_falls_back_when_docs_metadata_missing(monkeypatch) -> None:
    class DummyResponse:
        text = "<html><body><a href=\"https://github.blog/changelog\">Changelog</a></body></html>"

        def json(self):
            return {
                "info": {
                    "project_urls": {},
                    "home_page": None,
                    "version": "1.0.0",
                },
                "releases": {},
            }

    class DummyOperationalRepository:
        def get_service_status(self, service: str):
            return None

        def mark_service_status(self, service: str, status: str, retry_after=None) -> None:
            return None

    resolver = source_resolver.OfficialSourceResolver(DummyOperationalRepository())
    monkeypatch.setattr(resolver, "_request_with_retries", lambda url: DummyResponse())
    monkeypatch.setattr(source_resolver, "_extract_github_repo", lambda project_urls, home_page: "https://github.com/openai/openai-python")

    source_contract, symbol_lifecycles, release_history, migration_guides, pypi_json = resolver.resolve("openai", [])

    assert source_contract.official_docs == "https://github.com/openai/openai-python"
    assert source_contract.github_repo == "https://github.com/openai/openai-python"
    assert source_contract.latest_version == "1.0.0"
    assert symbol_lifecycles == []
    assert release_history == []
    assert migration_guides == []
    assert pypi_json["info"]["version"] == "1.0.0"

