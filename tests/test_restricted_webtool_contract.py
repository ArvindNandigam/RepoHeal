from unittest.mock import MagicMock

import httpx

from app.config import Settings
from app.discovery.document_extractor import fetch_page
from app.knowledge.repository import KnowledgeRepository
from app.routes.response_formatters import format_bulk_response
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
