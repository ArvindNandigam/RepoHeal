from unittest.mock import MagicMock
import socket
import json

import httpx
import pytest

from app.config import Settings
from app.discovery.document_extractor import fetch_page
from app.routes.health import health, health_head
from app.knowledge.repository import KnowledgeRepository
from app.routes.response_formatters import format_bulk_response
from app.routes.response_formatters import format_symbol_response
from app.services.cache import IntelligenceCache
from app.services.version_resolver import resolve_library_metadata
from app.validators.sources import is_approved_source_url


def test_bulk_contract_preserves_repoheal_result_shape():
    response = format_bulk_response(
        [
            {
                "library": "pandas",
                "status": "success",
                "result": {
                    "library": "pandas",
                    "latest_version": "2.2.0",
                    "intelligence_status": "ok",
                    "results": [],
                },
            }
        ]
    )

    assert response == {
        "results": [
            {
                "library": "pandas",
                "latest_version": "2.2.0",
                "intelligence_status": "ok",
                "intelligence_reason": None,
                "results": [],
            }
        ]
    }


def test_source_url_must_match_configured_domain(monkeypatch):
    settings = Settings(mongodb_uri="mongodb://example", allowed_domains=("docs.example.com",))
    monkeypatch.setattr("app.validators.sources.get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.validators.sources.socket.getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))],
    )

    assert is_approved_source_url("https://docs.example.com/guide")
    assert not is_approved_source_url("https://evil.example/guide")
    assert not is_approved_source_url("file:///etc/passwd")


def test_fetch_page_rejects_unapproved_url_before_http_request(monkeypatch):
    monkeypatch.setattr("app.discovery.document_extractor.is_approved_source_url", lambda url: False)
    client = MagicMock()
    monkeypatch.setattr(httpx, "Client", client)

    assert fetch_page("https://evil.example") is None
    client.assert_not_called()


def test_fetch_page_uses_tls_verification_and_no_unvalidated_redirects(monkeypatch):
    monkeypatch.setattr("app.discovery.document_extractor.is_approved_source_url", lambda url: True)
    response = MagicMock(text="<html>ok</html>")
    response.raise_for_status.return_value = None
    client = MagicMock()
    client.return_value.__enter__.return_value.get.return_value = response
    monkeypatch.setattr(httpx, "Client", client)

    assert fetch_page("https://docs.example.com", timeout=3) == "ok"
    client.assert_called_once_with(timeout=3, follow_redirects=False, verify=True)


def test_mongodb_evidence_ttl_uses_configured_retention():
    database = MagicMock()
    database.list_collection_names.return_value = ["symbols", "relationships", "evidence", "libraries"]
    repository = KnowledgeRepository(MagicMock(), "repoheal", cache_expiry_days=7)
    repository.database = database

    repository.ensure_indexes()

    evidence_calls = database["evidence"].create_index.call_args_list
    assert any(
        call.args == ("retrieved_at",) and call.kwargs["expireAfterSeconds"] == 7 * 86400
        for call in evidence_calls
    )


def test_single_and_bulk_responses_share_status_and_request_id_contract():
    payload = {
        "library": "pandas",
        "latest_version": "2.2.0",
        "status": "cached",
        "intelligence_status": "ok",
        "results": [],
    }

    single = format_symbol_response(payload, request_id="req-1")
    bulk = format_bulk_response(
        [{"library": "pandas", "status": "cached", "result": payload}],
        request_id="req-1",
    )

    assert single["request_id"] == bulk["request_id"] == "req-1"
    assert single["status"] == bulk["status"] == "cached"
    assert bulk["results"][0]["status"] == "cached"


def test_positive_and_negative_cache_entries_are_separate_and_expire():
    cache = IntelligenceCache(positive_ttl_seconds=60, negative_ttl_seconds=60)
    cache.put("pandas", ["pandas.DataFrame"], {"value": "positive"}, positive=True)
    cache.put("pandas", ["pandas.Series"], {"value": "negative"}, positive=False)

    assert cache.get("pandas", ["pandas.DataFrame"]) == ({"value": "positive"}, "positive")
    assert cache.get("pandas", ["pandas.Series"]) == ({"value": "negative"}, "negative")


def test_local_registry_is_used_when_pypi_is_unavailable(monkeypatch):
    class FailedClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, *_args, **_kwargs):
            raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "Client", lambda **_kwargs: FailedClient())

    metadata = resolve_library_metadata("pandas")

    assert metadata["official_docs"] == "https://pandas.pydata.org/docs/"
    assert metadata["github_repo"] == "https://github.com/pandas-dev/pandas"


def test_fetch_page_revalidates_redirect_destination(monkeypatch):
    monkeypatch.setattr(
        "app.discovery.document_extractor.is_approved_source_url",
        lambda url: url.startswith("https://docs.example.com"),
    )
    redirect = MagicMock(status_code=302, headers={"location": "https://evil.example/final"})
    client = MagicMock()
    client.return_value.__enter__.return_value.get.return_value = redirect
    monkeypatch.setattr(httpx, "Client", client)

    assert fetch_page("https://docs.example.com/start") is None


def test_health_head_matches_get_status_for_healthy_and_degraded(monkeypatch):
    settings = Settings(mongodb_uri="mongodb://example", service_version="test")
    monkeypatch.setattr("app.routes.health.get_settings", lambda: settings)
    request = MagicMock()
    request.app.state.start_time = None
    request.state.now = None

    repository = MagicMock(is_mongo_connected=True)
    repository.ping.return_value = True
    monkeypatch.setattr("app.routes.health.get_operational_repository", lambda: repository)

    healthy_get = health(request)
    healthy_head = health_head(request)
    assert healthy_get.status_code == healthy_head.status_code == 200
    assert json.loads(healthy_get.body)["status"] == "healthy"

    repository.is_mongo_connected = False
    degraded_get = health(request)
    degraded_head = health_head(request)
    assert degraded_get.status_code == degraded_head.status_code == 503
    assert json.loads(degraded_get.body)["status"] == "degraded"


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.8",
        "169.254.169.254",
        "::1",
        "fd00::1",
        "fe80::1",
        "2001:db8::1",
    ],
)
def test_source_url_rejects_non_public_resolved_addresses(monkeypatch, address):
    settings = Settings(mongodb_uri="mongodb://example", allowed_domains=("trusted.example",))
    monkeypatch.setattr("app.validators.sources.get_settings", lambda: settings)
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    monkeypatch.setattr(
        "app.validators.sources.socket.getaddrinfo",
        lambda *_args, **_kwargs: [(family, socket.SOCK_STREAM, 6, "", (address, 443))],
    )

    assert not is_approved_source_url("https://trusted.example/guide")


def test_source_url_rejects_docs_wildcard_and_userinfo(monkeypatch):
    settings = Settings(mongodb_uri="mongodb://example", allowed_domains=("docs.python.org",))
    monkeypatch.setattr("app.validators.sources.get_settings", lambda: settings)

    assert not is_approved_source_url("https://docs.attacker.example/guide")
    assert not is_approved_source_url("https://name@docs.python.org/guide")


@pytest.mark.anyio
async def test_symbol_errors_do_not_return_traceback_or_exception_details():
    from starlette.requests import Request
    from app.routes.symbol_intelligence import _resolve_symbol_intelligence

    async def receive():
        return {"type": "http.request", "body": b"{", "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/symbol-intelligence",
            "query_string": b"debug=true",
            "headers": [],
        },
        receive,
    )
    request.state.request_id = "req-security"

    response = await _resolve_symbol_intelligence(
        request,
        MagicMock(),
        MagicMock(),
        debug=True,
    )

    body = json.loads(response.body)
    assert body == {
        "request_id": "req-security",
        "status": "provider_unavailable",
        "reason": "failed_to_parse_request",
    }
