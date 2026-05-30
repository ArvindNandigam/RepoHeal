from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import dependencies
from app.main import app
from app.runtime_backends import InMemoryCacheRepository, InMemoryOperationalRepository
from app.services.library_intelligence import LibraryIntelligenceService
from app.services import source_resolver
from app.services.source_resolver import LibraryNotFoundError
from app.services.symbol_evidence_resolver import SymbolEvidenceResolver


class DummyRepository:
    def __init__(self) -> None:
        self.cached: dict[str, dict] = {}
        self.saved: list[tuple[str, str, dict]] = []
        self.symbols: dict[tuple[str, str], dict] = {}

    def get_library_payload(self, library: str, symbols: list[str]):
        return self.cached.get((library, tuple(sorted(symbols))))

    def upsert_library_payload(self, library: str, symbols: list[str], payload: dict) -> None:
        self.cached[(library, tuple(sorted(symbols)))] = payload

    def upsert_source_payload(self, library: str, source_type: str, payload: dict) -> None:
        self.saved.append((library, source_type, payload))

    def upsert_symbol_payload(self, library: str, symbol: str, payload: dict) -> None:
        self.saved.append((library, symbol, payload))

    def get_symbol_payload(self, library: str, symbol: str):
        return self.symbols.get((library, symbol))


class DummyResolver:
    def resolve(self, library: str, symbols: list[str]):
        source_contract = {
            "library": library,
            "official_docs": "https://docs.openai.com/",
            "github_repo": "https://github.com/openai/openai-python",
            "pypi_url": "https://pypi.org/pypi/openai/json",
            "latest_version": "1.52.0",
        }
        release_history = [{"version": "1.52.0", "url": "https://github.com/openai/openai-python/releases/tag/v1.52.0"}]
        migration_guides = [{"title": "Migration Guide", "url": "https://docs.openai.com/migration"}]
        symbol_lifecycles = [{"symbol": symbols[0], "introduced_version": "0.0.0", "deprecated_version": None, "removed_version": None, "replacement_symbol": None}] if symbols else []
        return source_contract, symbol_lifecycles, release_history, migration_guides, {}


class EvidenceResolverSource:
    def resolve_sources(self, library: str, trust_sources: bool = False):
        source_contract = {
            "library": library,
            "official_docs": "https://docs.openai.com/api",
            "github_repo": "https://github.com/openai/openai-python",
            "pypi_url": "https://pypi.org/pypi/openai/json",
            "latest_version": "1.52.0",
        }
        release_history = [{"version": "1.52.0", "url": "https://github.com/openai/openai-python/releases/tag/v1.52.0"}]
        migration_guides = [{"title": "Migration Guide", "url": "https://docs.openai.com/migration"}]
        return source_contract, release_history, migration_guides, {}

    def _request_with_retries(self, url: str):
        class Response:
            def __init__(self, text: str) -> None:
                self.text = text

        pages = {
            "https://docs.openai.com/api": "<html><body><h1>OpenAI API</h1><p>ChatCompletion.create is deprecated and renamed to client.chat.completions.create.</p></body></html>",
            "https://github.com/openai/openai-python": "<html><body><p>client.chat.completions.create is the new method.</p></body></html>",
            "https://github.com/openai/openai-python/releases/tag/v1.52.0": "<html><body><p>Removed ChatCompletion.create in 1.52.0. Use client.chat.completions.create instead.</p></body></html>",
            "https://docs.openai.com/migration": "<html><body><p>ChatCompletion.create was renamed to client.chat.completions.create.</p></body></html>",
        }
        return Response(pages[url])


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


def test_service_resolve_symbol_uses_symbol_cache_when_present() -> None:
    repository = DummyRepository()
    repository.symbols[("openai", "openai.ChatCompletion.create")] = {
        "symbol": "openai.ChatCompletion.create",
        "lifecycle": "removed",
        "confidence": 1.0,
        "evidence": [{"type": "migration_guide", "url": "https://docs.openai.com/migration", "matched_text": "ChatCompletion.create was renamed to client.chat.completions.create."}],
    }
    service = LibraryIntelligenceService(repository, DummyOperationalRepository(), DummyResolver())

    result = service.resolve_symbol("openai", "openai.ChatCompletion.create")

    assert result["lifecycle"] == "removed"
    assert service.last_cache_hit is True


def test_symbol_evidence_resolver_extracts_evidence_and_versions() -> None:
    resolver = SymbolEvidenceResolver(EvidenceResolverSource())

    result = resolver.resolve_from_source_bundle(
        "openai",
        ["openai.ChatCompletion.create"],
        {
            "source_contract": {
                "library": "openai",
                "official_docs": "https://docs.openai.com/api",
                "github_repo": "https://github.com/openai/openai-python",
                "pypi_url": "https://pypi.org/pypi/openai/json",
                "latest_version": "1.52.0",
            },
            "release_history": [{"version": "1.52.0", "url": "https://github.com/openai/openai-python/releases/tag/v1.52.0"}],
            "migration_guides": [{"title": "Migration Guide", "url": "https://docs.openai.com/migration"}],
            "pypi_json": {},
        },
    )

    assert len(result) == 1
    lifecycle = result[0]
    assert lifecycle["symbol"] == "openai.ChatCompletion.create"
    assert lifecycle["confidence"] == 1.0
    assert lifecycle["removed_version"] == "1.52.0"
    assert lifecycle["replacement_symbol"] == "client.chat.completions.create"
    assert lifecycle["evidence"]
    assert all("url" in item for item in lifecycle["evidence"])


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

    assert source_contract["official_docs"] == "https://github.com/openai/openai-python"
    assert source_contract["github_repo"] == "https://github.com/openai/openai-python"
    assert source_contract["latest_version"] == "1.0.0"
    assert symbol_lifecycles == []
    assert release_history == []
    assert migration_guides == []
    assert pypi_json["info"]["version"] == "1.0.0"


def test_source_resolver_prefers_real_github_repo_and_dedupes_guides(monkeypatch) -> None:
    class DummyResponse:
        text = "<html><body><a href=\"https://github.com/openai/openai-python/blob/main/CHANGELOG.md\">CHANGELOG.md</a></body></html>"

        def json(self):
            return {
                "info": {
                    "project_urls": {
                        "Sponsor": "https://github.com/sponsors/samuelcolvin",
                        "Repository": "https://github.com/openai/openai-python",
                        "Changelog": "https://github.com/openai/openai-python/blob/main/CHANGELOG.md",
                    },
                    "home_page": "https://github.com/sponsors/samuelcolvin",
                    "version": "2.0.0",
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

    source_contract, symbol_lifecycles, release_history, migration_guides, pypi_json = resolver.resolve("openai", [])

    assert source_contract["github_repo"] == "https://github.com/openai/openai-python"
    assert source_contract["official_docs"] == "https://github.com/openai/openai-python"
    assert [guide["title"] for guide in migration_guides] == ["Changelog"]
    assert [guide["url"] for guide in migration_guides] == ["https://github.com/openai/openai-python/blob/main/CHANGELOG.md"]
    assert symbol_lifecycles == []
    assert release_history == []
    assert pypi_json["info"]["version"] == "2.0.0"


def test_source_resolver_raises_library_not_found_on_pypi_404(monkeypatch) -> None:
    class DummyResponse:
        status_code = 404

        def raise_for_status(self):
            raise source_resolver.httpx.HTTPStatusError(
                "not found",
                request=source_resolver.httpx.Request("GET", "https://pypi.org/pypi/missing-package/json"),
                response=DummyResponse(),
            )

    class DummyOperationalRepository:
        def get_service_status(self, service: str):
            return None

        def mark_service_status(self, service: str, status: str, retry_after=None) -> None:
            return None

    resolver = source_resolver.OfficialSourceResolver(DummyOperationalRepository())
    monkeypatch.setattr(resolver, "_request_with_retries", lambda url: (_ for _ in ()).throw(LibraryNotFoundError("missing-package")))

    try:
        resolver.resolve("missing-package", [])
    except LibraryNotFoundError:
        return

    raise AssertionError("LibraryNotFoundError was not raised")


def test_library_route_returns_library_not_found(monkeypatch) -> None:
    class FailingService:
        last_cache_hit = False

        def resolve(self, library: str, symbols: list[str]):
            raise LibraryNotFoundError(library)

    app.dependency_overrides.clear()
    app.dependency_overrides[dependencies.get_library_intelligence_service] = lambda: FailingService()

    try:
        client = TestClient(app)
        response = client.post(
            "/library-intelligence",
            headers={"Authorization": "Bearer vT5X3du/efIgYBGtXSC1B++jlF/7vszfSl6EtcE/wzLIQgjLZ7qyvtamNE7ZhqxI"},
            json={"library": "missing-package"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json() == {"status": "failed", "reason": "library_not_found"}


def test_library_route_returns_condensed_payload(monkeypatch) -> None:
    class CondensedService:
        last_cache_hit = False

        def resolve(self, library: str, symbols: list[str]):
            return {
                "library": library,
                "latest_version": "1.52.0",
                "official_docs": "https://docs.openai.com/",
                "github_repo": "https://github.com/openai/openai-python",
                "pypi_url": "https://pypi.org/pypi/openai/json",
                "symbol_lifecycles": [{"symbol": "openai.ChatCompletion.create", "confidence": 0.97, "evidence": []}],
                "release_history": [{"version": "1.52.0", "url": "https://github.com/openai/openai-python/releases/tag/v1.52.0"}],
                "migration_guides": [{"title": "Migration Guide", "url": "https://docs.openai.com/migration"}],
            }

    class OperationalRepositoryStub:
        def log_audit_event(self, *args, **kwargs) -> None:
            return None

    app.dependency_overrides.clear()
    app.dependency_overrides[dependencies.get_library_intelligence_service] = lambda: CondensedService()
    app.dependency_overrides[dependencies.get_operational_repository] = lambda: OperationalRepositoryStub()

    try:
        client = TestClient(app)
        response = client.post(
            "/library-intelligence",
            headers={"Authorization": "Bearer vT5X3du/efIgYBGtXSC1B++jlF/7vszfSl6EtcE/wzLIQgjLZ7qyvtamNE7ZhqxI"},
            json={"library": "openai"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "library": "openai",
        "latest_version": "1.52.0",
        "official_docs": "https://docs.openai.com/",
        "github_repo": "https://github.com/openai/openai-python",
    }


def test_bulk_route_returns_condensed_results(monkeypatch) -> None:
    class CondensedService:
        last_cache_hit = False

        def resolve(self, library: str, symbols: list[str]):
            version = {"openai": "1.52.0", "fastapi": "0.136.3"}.get(library, "0.0.0")
            return {
                "library": library,
                "latest_version": version,
                "official_docs": "https://example.org/docs",
                "github_repo": "https://example.org/repo",
                "pypi_url": "https://example.org/pypi",
                "symbol_lifecycles": [],
                "release_history": [],
                "migration_guides": [],
            }

    class OperationalRepositoryStub:
        def log_audit_event(self, *args, **kwargs) -> None:
            return None

        def log_error(self, *args, **kwargs) -> None:
            return None

    app.dependency_overrides.clear()
    app.dependency_overrides[dependencies.get_library_intelligence_service] = lambda: CondensedService()
    app.dependency_overrides[dependencies.get_operational_repository] = lambda: OperationalRepositoryStub()

    try:
        client = TestClient(app)
        response = client.post(
            "/bulk-library-intelligence",
            headers={"Authorization": "Bearer vT5X3du/efIgYBGtXSC1B++jlF/7vszfSl6EtcE/wzLIQgjLZ7qyvtamNE7ZhqxI"},
            json={"libraries": [{"library": "openai"}, {"library": "fastapi"}]},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "results": [
            {"library": "openai", "latest_version": "1.52.0"},
            {"library": "fastapi", "latest_version": "0.136.3"},
        ]
    }


def test_symbol_route_accepts_symbols_list(monkeypatch) -> None:
    class FailingOperationalRepository:
        def log_audit_event(self, *args, **kwargs) -> None:
            return None

    class MultiSymbolService:
        last_cache_hit = False

        def resolve(self, library: str, symbols: list[str]):
            return {
                "library": library,
                "latest_version": "1.52.0",
                "official_docs": "https://docs.openai.com/",
                "github_repo": "https://github.com/openai/openai-python",
                "pypi_url": "https://pypi.org/pypi/openai/json",
                "symbol_lifecycles": [
                    {"symbol": symbol, "lifecycle": "inferred", "confidence": 0.5, "evidence": []}
                    for symbol in symbols
                ],
                "release_history": [],
                "migration_guides": [],
            }

        def resolve_symbol(self, library: str, symbol: str):
            return {"symbol": symbol, "lifecycle": "inferred", "confidence": 0.5, "evidence": []}

    app.dependency_overrides.clear()
    app.dependency_overrides[dependencies.get_library_intelligence_service] = lambda: MultiSymbolService()
    app.dependency_overrides[dependencies.get_operational_repository] = lambda: FailingOperationalRepository()

    try:
        client = TestClient(app)
        response = client.post(
            "/symbol-intelligence",
            headers={"Authorization": "Bearer vT5X3du/efIgYBGtXSC1B++jlF/7vszfSl6EtcE/wzLIQgjLZ7qyvtamNE7ZhqxI"},
            json={"library": "openai", "symbols": ["openai.ChatCompletion.create", "openai.Embedding.create"]},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["library"] == "openai"
    assert payload["latest_version"] == "1.52.0"
    assert [item["symbol"] for item in payload["symbols"]] == ["openai.ChatCompletion.create", "openai.Embedding.create"]
    assert "symbol_lifecycles" not in payload


def test_symbol_route_debug_includes_sources_and_evidence(monkeypatch) -> None:
    class OperationalRepositoryStub:
        def log_audit_event(self, *args, **kwargs) -> None:
            return None

    class DebugService:
        last_cache_hit = False

        def resolve(self, library: str, symbols: list[str]):
            return {
                "library": library,
                "latest_version": "1.52.0",
                "official_docs": "https://docs.openai.com/",
                "github_repo": "https://github.com/openai/openai-python",
                "pypi_url": "https://pypi.org/pypi/openai/json",
                "symbol_lifecycles": [
                    {
                        "symbol": symbols[0],
                        "introduced_version": "0.0.0",
                        "deprecated_version": None,
                        "removed_version": "1.0.0",
                        "replacement_symbol": "client.chat.completions.create",
                        "confidence": 0.97,
                        "evidence": [{"type": "migration_guide", "url": "https://docs.openai.com/migration", "matched_text": "omitted"}],
                    }
                ],
                "release_history": [{"version": "1.52.0", "url": "https://github.com/openai/openai-python/releases/tag/v1.52.0"}],
                "migration_guides": [{"title": "Migration Guide", "url": "https://docs.openai.com/migration"}],
            }

    app.dependency_overrides.clear()
    app.dependency_overrides[dependencies.get_library_intelligence_service] = lambda: DebugService()
    app.dependency_overrides[dependencies.get_operational_repository] = lambda: OperationalRepositoryStub()

    try:
        client = TestClient(app)
        response = client.post(
            "/symbol-intelligence?debug=true",
            headers={"Authorization": "Bearer vT5X3du/efIgYBGtXSC1B++jlF/7vszfSl6EtcE/wzLIQgjLZ7qyvtamNE7ZhqxI"},
            json={"library": "openai", "symbols": ["openai.ChatCompletion.create"]},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["sources"]
    assert payload["evidence"]
    assert all("url" in item for item in payload["sources"])
    assert all("url" in item for item in payload["evidence"])
    assert "matched_text" not in str(payload)

