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


def _collect_debug_event_data(symbol_lifecycles: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], int, int]:
    attempts: list[dict[str, Any]] = []
    matches: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    searched_urls: set[str] = set()
    used_urls: set[str] = set()

    for lifecycle in symbol_lifecycles:
        debug_info = lifecycle.get("_debug") if isinstance(lifecycle.get("_debug"), dict) else {}
        for attempt in debug_info.get("event_extraction_attempts") or []:
            if isinstance(attempt, dict):
                attempts.append(
                    {
                        "symbol": lifecycle.get("symbol"),
                        "document": attempt.get("document"),
                        "url": attempt.get("url"),
                        "matches_found": attempt.get("matches_found", 0),
                    }
                )
                if attempt.get("url"):
                    searched_urls.add(str(attempt.get("url")))

        for match in debug_info.get("event_extraction_matches") or []:
            if not isinstance(match, dict):
                continue
            matches.append(
                {
                    "symbol": lifecycle.get("symbol"),
                    "document": match.get("document"),
                    "url": match.get("url"),
                    "matched_text": match.get("matched_text"),
                    "event_type_detected": match.get("event_type_detected"),
                    "accepted": bool(match.get("accepted")),
                    **({"rejection_reason": match.get("rejection_reason")} if not match.get("accepted") and match.get("rejection_reason") else {}),
                }
            )
            if match.get("accepted") and match.get("url"):
                used_urls.add(str(match.get("url")))

        for item in debug_info.get("evidence_rejected") or []:
            if not isinstance(item, dict):
                continue
            rejected.append(
                {
                    "matched_text": item.get("matched_text"),
                    "rejection_reason": item.get("rejection_reason"),
                }
            )

    return attempts, matches, rejected, len(searched_urls), len(used_urls)


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


def _format_migration_event(event: dict[str, Any], debug: bool = False) -> dict[str, Any]:
    response = {
        "event_type": event.get("event_type"),
        "version": event.get("version"),
        "source_type": event.get("source_type"),
        "title": event.get("title"),
        "url": event.get("url"),
    }
    if debug:
        response["matched_text"] = event.get("matched_text")
    return response


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
    return {
        "symbol": lifecycle.get("symbol"),
        "evidence_count": len(evidence),
        "versions_observed": lifecycle.get("versions_observed") or [],
        "earliest_version_found": lifecycle.get("earliest_version_found"),
        "latest_version_found": lifecycle.get("latest_version_found"),
        "evidence_sources": _evidence_source_summary(evidence),
        "migration_events": [_format_migration_event(event, debug=False) for event in (lifecycle.get("migration_events") or [])],
    }


def _format_symbol_entry_debug(lifecycle: dict[str, Any]) -> dict[str, Any]:
    evidence = lifecycle.get("evidence") if isinstance(lifecycle.get("evidence"), list) else []
    debug_info = lifecycle.get("_debug") if isinstance(lifecycle.get("_debug"), dict) else {}
    return {
        "symbol": lifecycle.get("symbol"),
        "evidence": evidence,
        "evidence_sources": _evidence_source_summary(evidence),
        "migration_events": [_format_migration_event(event, debug=True) for event in (lifecycle.get("migration_events") or [])],
        "event_extraction_attempts": [
            {
                "document": attempt.get("document"),
                "url": attempt.get("url"),
                "matches_found": attempt.get("matches_found", 0),
            }
            for attempt in (debug_info.get("event_extraction_attempts") or [])
        ],
        "event_extraction_matches": [
            {
                "matched_text": match.get("matched_text"),
                "event_type_detected": match.get("event_type_detected"),
                "accepted": bool(match.get("accepted")),
                **({"rejection_reason": match.get("rejection_reason")} if not match.get("accepted") and match.get("rejection_reason") else {}),
            }
            for match in (debug_info.get("event_extraction_matches") or [])
        ],
        "evidence_rejected": [
            {
                "matched_text": item.get("matched_text"),
                "rejection_reason": item.get("rejection_reason"),
            }
            for item in (debug_info.get("evidence_rejected") or [])
        ],
        "migration_documents_searched": debug_info.get("migration_documents_searched", 0),
        "migration_documents_used": debug_info.get("migration_documents_used", 0),
    }


def format_symbol_response(payload: dict[str, Any], debug: bool = False, cache_hit: bool | None = None, cache_collection: str = "symbol_cache") -> dict[str, Any]:
    symbol_lifecycles = payload.get("symbol_lifecycles")
    if not isinstance(symbol_lifecycles, list):
        symbol_lifecycles = [payload]

    response = {
        "library": payload.get("library"),
        "latest_version": payload.get("latest_version"),
        "symbols": [
            _format_symbol_entry_debug(lifecycle) if debug else _format_symbol_entry(lifecycle)
            for lifecycle in symbol_lifecycles
        ],
    }

    if debug:
        debug_documents = _collect_debug_documents(payload.get("migration_guides") or [])
        attempts, matches, rejected, searched_count, used_count = _collect_debug_event_data(symbol_lifecycles)
        debug_documents["migration_documents_searched"] = searched_count
        debug_documents["migration_documents_used"] = used_count
        debug_documents["event_extraction_attempts"] = attempts
        debug_documents["event_extraction_matches"] = matches
        debug_documents["evidence_rejected"] = rejected
        debug_documents["cache_hit"] = bool(cache_hit)
        debug_documents["cache_collection"] = cache_collection
        response["debug"] = debug_documents

    return response