from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def _is_truthy_debug(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def is_debug_enabled(query_params: Any) -> bool:
    return _is_truthy_debug(getattr(query_params, "get", lambda _key, default=None: default)("debug", None))


def _unique_items(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for item in items:
        key = tuple(sorted(item.items()))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _collect_sources(payload: dict[str, Any]) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []

    if payload.get("official_docs"):
        sources.append({"type": "official_docs", "url": str(payload["official_docs"])})
    if payload.get("github_repo"):
        sources.append({"type": "github_repo", "url": str(payload["github_repo"])})
    if payload.get("pypi_url"):
        sources.append({"type": "pypi", "url": str(payload["pypi_url"])})

    for release in payload.get("release_history") or []:
        url = release.get("url")
        if url:
            sources.append({"type": "release_history", "url": str(url)})

    for guide in payload.get("migration_guides") or []:
        url = guide.get("url")
        if url:
            sources.append({"type": "migration_guide", "url": str(url)})

    return _unique_items(sources)


def _collect_symbol_evidence(symbol_lifecycles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence_items: list[dict[str, Any]] = []
    for lifecycle in symbol_lifecycles:
        for evidence in lifecycle.get("evidence") or []:
            url = evidence.get("url")
            if not url:
                continue
            evidence_items.append(
                {
                    "symbol": str(lifecycle.get("symbol", "")),
                    "version": evidence.get("version"),
                    "source_type": str(evidence.get("source_type", evidence.get("type", "evidence"))),
                    "url": str(url),
                    "matched_text": str(evidence.get("matched_text", "")),
                }
            )
    return _unique_items(evidence_items)


def _collect_migration_documents(migration_guides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for guide in migration_guides:
        url = guide.get("url")
        if not url:
            continue
        documents.append(
            {
                "title": guide.get("title"),
                "url": str(url),
                "source_type": str(guide.get("source_type", "migration_guide")),
            }
        )
    return _unique_items(documents)


def _collect_symbol_migration_documents(symbol_lifecycles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for lifecycle in symbol_lifecycles:
        for document in lifecycle.get("migration_documents") or []:
            url = document.get("url")
            if not url:
                continue
            documents.append(
                {
                    "title": document.get("title"),
                    "url": str(url),
                    "source_type": str(document.get("source_type", "migration_guide")),
                }
            )
    return _unique_items(documents)


def _document_matches_bucket(document: dict[str, Any], bucket: str) -> bool:
    source_type = str(document.get("source_type") or "").lower()
    title = str(document.get("title") or "").lower()
    url = str(document.get("url") or "").lower()

    if bucket == "release_notes":
        return source_type == "release_notes" or "release note" in title or "release note" in url
    if bucket == "changelogs":
        return source_type == "changelog" or "changelog" in title or "changelog" in url
    if bucket == "deprecation_docs":
        return source_type == "official_deprecation_notice" or "deprecat" in title or "deprecat" in url
    return False


def _collect_debug_documents(migration_guides: list[dict[str, Any]]) -> dict[str, Any]:
    migration_documents = _collect_migration_documents(migration_guides)
    return {
        "migration_documents_discovered": migration_documents,
        "migration_documents_found": migration_documents,
        "migration_documents_searched": 0,
        "migration_documents_used": 0,
        "release_notes_discovered": [document for document in migration_documents if _document_matches_bucket(document, "release_notes")],
        "changelogs_discovered": [document for document in migration_documents if _document_matches_bucket(document, "changelogs")],
        "deprecation_docs_discovered": [document for document in migration_documents if _document_matches_bucket(document, "deprecation_docs")],
    }


def _evidence_source_summary(evidence: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "migration_guides": 0,
        "release_notes": 0,
        "changelogs": 0,
        "deprecation_notices": 0,
        "versioned_docs": 0,
    }
    source_map = {
        "migration_guide": "migration_guides",
        "release_notes": "release_notes",
        "changelog": "changelogs",
        "official_deprecation_notice": "deprecation_notices",
        "versioned_docs": "versioned_docs",
    }
    seen: set[tuple[Any, ...]] = set()
    for item in evidence:
        key = (item.get("source_type"), item.get("version"), item.get("url"), item.get("matched_text"))
        if key in seen:
            continue
        seen.add(key)
        source_key = source_map.get(str(item.get("source_type")))
        if source_key:
            summary[source_key] += 1
    return summary


def format_library_response(payload: dict[str, Any], debug: bool = False) -> dict[str, Any]:
    response = {
        "library": payload["library"],
        "latest_version": payload["latest_version"],
        "official_docs": payload["official_docs"],
        "github_repo": payload["github_repo"],
    }
    if debug:
        response["sources"] = _collect_sources(payload)
        response["evidence"] = _collect_symbol_evidence(payload.get("symbol_lifecycles") or [])
    return response


def format_bulk_response(result_items: list[dict[str, Any]]) -> dict[str, Any]:
    formatted_results: list[dict[str, Any]] = []
    for item in result_items:
        if item.get("status") == "success" and isinstance(item.get("result"), dict):
            formatted_results.append(
                {
                    "library": item["library"],
                    "latest_version": item["result"].get("latest_version"),
                }
            )
            continue

        formatted_results.append(
            {
                "library": item["library"],
                "status": item.get("status", "failed"),
                "reason": item.get("reason", "source_unavailable"),
            }
        )

    return {"results": formatted_results}


def _format_symbol_entry(lifecycle: dict[str, Any]) -> dict[str, Any]:
    evidence = lifecycle.get("evidence") if isinstance(lifecycle.get("evidence"), list) else []
    evidence_preview = [
        {
            "version": evidence_item.get("version"),
            "source_type": str(evidence_item.get("source_type", evidence_item.get("type", "evidence"))),
            "url": str(evidence_item.get("url", "")),
            "matched_text": str(evidence_item.get("matched_text", "")),
            "match_reason": str(evidence_item.get("match_reason", "")),
        }
        for evidence_item in evidence[:5]
        if evidence_item.get("url")
    ]
    return {
        "symbol": lifecycle.get("symbol"),
        "evidence_count": len(evidence),
        "versions_observed": lifecycle.get("versions_observed") or [],
        "migration_document_count": len(lifecycle.get("migration_documents") or []),
        "evidence_preview": evidence_preview,
        "evidence_quality": lifecycle.get("evidence_quality") or {
            "exact_symbol_matches": 0,
            "tail_matches": 0,
            "api_reference_matches": 0,
            "confidence": "low",
        },
    }


def _format_symbol_entry_debug(lifecycle: dict[str, Any]) -> dict[str, Any]:
    evidence = lifecycle.get("evidence") if isinstance(lifecycle.get("evidence"), list) else []
    return {
        "symbol": lifecycle.get("symbol"),
        "evidence": evidence,
        "migration_documents": lifecycle.get("migration_documents") or [],
        "evidence_rejected": (lifecycle.get("_debug") or {}).get("evidence_rejected") or [],
        "evidence_quality": lifecycle.get("evidence_quality") or {
            "exact_symbol_matches": 0,
            "tail_matches": 0,
            "api_reference_matches": 0,
            "confidence": "low",
        },
    }


def format_symbol_response(payload: dict[str, Any], debug: bool = False, cache_hit: bool | None = None, cache_collection: str = "symbol_cache") -> dict[str, Any]:
    symbol_lifecycles = payload.get("symbol_lifecycles")
    if not isinstance(symbol_lifecycles, list):
        symbol_lifecycles = [payload]

    migration_documents = _collect_migration_documents(payload.get("migration_guides") or [])

    if debug and len(symbol_lifecycles) == 1:
        symbol_entry = _format_symbol_entry_debug(symbol_lifecycles[0])
        return {
            "library": payload.get("library"),
            "latest_version": payload.get("latest_version"),
            **symbol_entry,
            "migration_documents": migration_documents,
        }

    response = {
        "library": payload.get("library"),
        "latest_version": payload.get("latest_version"),
        "symbols": [_format_symbol_entry_debug(lifecycle) if debug else _format_symbol_entry(lifecycle) for lifecycle in symbol_lifecycles],
        "migration_documents": migration_documents,
    }

    return response