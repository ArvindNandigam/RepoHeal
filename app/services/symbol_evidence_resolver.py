from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from typing import Any

from packaging.version import InvalidVersion, Version

from app.validators.sources import is_approved_source_url

EXPLICIT_EVIDENCE_SOURCES = {"migration_guide", "changelog", "release_notes", "official_deprecation_notice", "versioned_docs"}
SOURCE_PRIORITY = {
    "migration_guide": 0,
    "official_deprecation_notice": 1,
    "changelog": 2,
    "release_notes": 3,
    "versioned_docs": 4,
}
MIGRATION_EVENT_PATTERNS = {
    "deprecated": re.compile(r"\bdeprecat(?:ed|e|ion)\b", flags=re.IGNORECASE),
    "removed": re.compile(r"\bremoved\b|\bno longer supported\b|\bdeleted\b", flags=re.IGNORECASE),
    "replaced": re.compile(r"\breplaced\b|\breplaced by\b|\buse instead\b|\bmigrated to\b|\brenamed to\b", flags=re.IGNORECASE),
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)

    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.parts)).strip()


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _extract_text(content: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(content)
    text = extractor.text()
    return text or _normalize_whitespace(content)


def _symbol_candidates(symbol: str) -> list[str]:
    normalized = symbol.strip()
    if not normalized:
        return []

    candidates = [normalized]
    parts = [part for part in normalized.split(".") if part]
    if len(parts) >= 2:
        candidates.append(".".join(parts[-2:]))

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _symbol_match_terms(symbol: str) -> list[str]:
    return [term.lower() for term in _symbol_candidates(symbol)]


def _snippet_mentions_symbol(snippet: str, symbol: str) -> bool:
    lowered = snippet.lower()
    return any(term in lowered for term in _symbol_match_terms(symbol))


def _snippet(text: str, start: int, length: int, window: int = 140) -> str:
    snippet_start = max(0, start - window)
    snippet_end = min(len(text), start + length + window)
    return _normalize_whitespace(text[snippet_start:snippet_end])


def _focus_snippet_to_sentence(snippet: str, symbol: str) -> str:
    lowered = snippet.lower()
    terms = _symbol_match_terms(symbol)
    positions = [lowered.find(term) for term in terms if term in lowered]
    if not positions:
        return snippet

    match_index = min(position for position in positions if position >= 0)
    sentence_start = 0
    for delimiter in (". ", "! ", "? ", "\n"):
        position = snippet.rfind(delimiter, 0, match_index)
        if position > sentence_start:
            sentence_start = position + len(delimiter)

    sentence_end = len(snippet)
    for delimiter in (". ", "! ", "? ", "\n"):
        position = snippet.find(delimiter, match_index)
        if position != -1:
            sentence_end = min(sentence_end, position + len(delimiter.strip()))

    focused = snippet[sentence_start:sentence_end].strip()
    return focused or snippet


def _evidence_relevance_score(source_kind: str) -> float:
    if source_kind in {"migration_guide", "official_deprecation_notice"}:
        return 0.95
    if source_kind == "changelog":
        return 0.9
    if source_kind == "release_notes":
        return 0.85
    return 0.0


def _extract_version(text: str, fallback: str | None = None) -> str | None:
    if fallback and _is_valid_version(fallback):
        return fallback

    patterns = (
        r"(?:version|v)\s*(\d+(?:\.\d+){0,3}(?:[a-z0-9.-]+)?)",
        r"(?:introduced|added|deprecated|removed|released|renamed|available)\s+(?:in\s+)?(?:version\s+)?v?(\d+(?:\.\d+){0,3}(?:[a-z0-9.-]+)?)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).rstrip(".,;:)[]")
    return None


def _version_sort_key(value: str) -> tuple[int, Any]:
    try:
        return (0, Version(value))
    except InvalidVersion:
        return (1, value)


def _is_valid_version(value: str | None) -> bool:
    if not value:
        return False

    candidate = value.strip().rstrip(".,;:)[]")
    if not candidate or "." not in candidate:
        return False

    try:
        Version(candidate)
    except InvalidVersion:
        return False
    return True


def _ordered_unique_versions(values: list[str | None]) -> list[str]:
    versions = {value for value in values if value and _is_valid_version(value)}
    return sorted(versions, key=_version_sort_key)


def _detect_migration_event_types(text: str) -> list[str]:
    event_types: list[str] = []
    for event_type, pattern in MIGRATION_EVENT_PATTERNS.items():
        if pattern.search(text):
            event_types.append(event_type)
    return event_types


def _dedupe_records(items: list[dict[str, Any]], sort_key) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for item in sorted(items, key=sort_key):
        key = tuple(item.get(field) for field in ("event_type", "version", "source_type", "title", "url", "matched_text"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _discover_versioned_docs(source_bundle: dict[str, Any]) -> list[dict[str, str | None]]:
    source_contract = source_bundle.get("source_contract") or {}
    official_docs = str(source_contract.get("official_docs") or "")
    release_history = source_bundle.get("release_history") or []

    if not official_docs:
        return []

    versioned_pages: list[dict[str, str | None]] = []
    version_templates = []
    if "/en/latest/" in official_docs:
        version_templates.append(("/en/latest/", "/en/{version}/"))
    if "/en/stable/" in official_docs:
        version_templates.append(("/en/stable/", "/en/{version}/"))
    if official_docs.rstrip("/").endswith("/latest"):
        version_templates.append(("/latest", "/{version}"))
    if official_docs.rstrip("/").endswith("/stable"):
        version_templates.append(("/stable", "/{version}"))

    if not version_templates:
        return []

    versions = _ordered_unique_versions([str(entry.get("version")) for entry in release_history if entry.get("version")])
    for version in (versions or []):
        for old, new in version_templates:
            candidate = official_docs.replace(old, new.format(version=version), 1)
            if candidate != official_docs and is_approved_source_url(candidate):
                versioned_pages.append({"type": "versioned_docs", "url": candidate, "release_version": version})
                break

    return versioned_pages


class SymbolEvidenceResolver:
    def __init__(self, source_resolver: Any) -> None:
        self.source_resolver = source_resolver

    def _build_pages(self, source_bundle: dict[str, Any]) -> list[dict[str, str | None]]:
        pages: list[dict[str, str | None]] = []

        for guide in source_bundle.get("migration_guides") or []:
            title = guide.get("title", "").lower()
            guide_type = "changelog" if "changelog" in title else "migration_guide"
            if "release notes" in title:
                guide_type = "release_notes"
            elif "deprecat" in title:
                guide_type = "official_deprecation_notice"
            elif any(token in title for token in ("api reference", "reference", "api docs")):
                continue
            pages.append({"type": guide_type, "url": guide["url"], "release_version": None, "title": guide.get("title")})

        for entry in source_bundle.get("release_history") or []:
            release_version = entry.get("version")
            pages.append(
                {
                    "type": "release_notes",
                    "url": entry["url"],
                    "release_version": release_version,
                    "title": entry.get("title") or (f"Release notes {release_version}" if release_version else "Release notes"),
                }
            )

        pages.extend(_discover_versioned_docs(source_bundle))

        seen: set[str] = set()
        deduped: list[dict[str, str | None]] = []
        for page in pages:
            url = str(page["url"])
            if url in seen:
                continue
            seen.add(url)
            deduped.append(page)

        priority = {
            "migration_guide": 0,
            "official_deprecation_notice": 1,
            "release_notes": 2,
            "changelog": 3,
            "versioned_docs": 4,
        }
        return sorted(
            deduped,
            key=lambda page: (
                priority.get(str(page.get("type") or ""), 99),
                str(page.get("title") or ""),
                str(page.get("url") or ""),
            ),
        )

    def _page_title(self, page: dict[str, str | None]) -> str:
        title = str(page.get("title") or "").strip()
        if title:
            return title
        page_type = str(page.get("type") or "").replace("_", " ").strip()
        return page_type.title() if page_type else "Source"

    def _fetch_page_text(self, url: str) -> str | None:
        if not is_approved_source_url(url):
            return None
        try:
            response = self.source_resolver._request_with_retries(url)
            return _extract_text(response.text)
        except Exception:
            return None

    def _find_snippets(self, text: str, symbol: str) -> list[str]:
        snippets: list[str] = []
        lowered = text.lower()
        for candidate in _symbol_candidates(symbol):
            candidate_lower = candidate.lower()
            start = 0
            while True:
                index = lowered.find(candidate_lower, start)
                if index < 0:
                    break
                snippets.append(_focus_snippet_to_sentence(_snippet(text, index, len(candidate)), symbol))
                start = index + max(1, len(candidate_lower))
        deduped: list[str] = []
        seen: set[str] = set()
        for snippet in snippets:
            key = snippet.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(snippet)
        return deduped

    def _build_migration_events(self, page: dict[str, str | None], snippet: str, source_type: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        version = _extract_version(snippet, fallback=page.get("release_version"))
        document = self._page_title(page)
        url = str(page["url"])
        if not _is_valid_version(version):
            return [], [
                {
                    "document": document,
                    "url": url,
                    "matched_text": snippet,
                    "event_type_detected": None,
                    "accepted": False,
                    "rejection_reason": "invalid_version",
                }
            ]

        events: list[dict[str, Any]] = []
        matches: list[dict[str, Any]] = []
        for event_type in _detect_migration_event_types(snippet):
            events.append(
                {
                    "event_type": event_type,
                    "version": version,
                    "source_type": source_type,
                    "title": document,
                    "url": url,
                    "matched_text": snippet,
                }
            )
            matches.append(
                {
                    "document": document,
                    "url": url,
                    "matched_text": snippet,
                    "event_type_detected": event_type,
                    "accepted": True,
                }
            )

        if not matches:
            matches.append(
                {
                    "document": document,
                    "url": url,
                    "matched_text": snippet,
                    "event_type_detected": None,
                    "accepted": False,
                    "rejection_reason": "no explicit event keyword",
                }
            )

        return events, matches

    def _build_evidence_rejection(self, snippet: str, symbol: str) -> dict[str, Any] | None:
        if _snippet_mentions_symbol(snippet, symbol):
            return None
        return {
            "matched_text": snippet,
            "rejection_reason": "symbol_not_present",
        }

    def resolve(self, library: str, symbols: list[str]) -> list[dict[str, Any]]:
        source_contract, release_history, migration_guides, pypi_json = self.source_resolver.resolve_sources(library)
        bundle = {
            "source_contract": source_contract,
            "release_history": release_history,
            "migration_guides": migration_guides,
            "pypi_json": pypi_json,
        }
        return self.resolve_from_source_bundle(library, symbols, bundle)

    def resolve_from_source_bundle(self, library: str, symbols: list[str], source_bundle: dict[str, Any]) -> list[dict[str, Any]]:
        pages = self._build_pages(source_bundle)
        latest_version = str((source_bundle.get("source_contract") or {}).get("latest_version") or "")
        results: list[dict[str, Any]] = [
            {
                "symbol": symbol,
                "versions_observed": [],
                "earliest_version_found": None,
                "latest_version_found": None,
                "evidence": [],
                "migration_events": [],
                "_debug": {
                    "event_extraction_attempts": [],
                    "event_extraction_matches": [],
                    "evidence_rejected": [],
                },
            }
            for symbol in symbols
        ]
        results_by_symbol = {entry["symbol"]: entry for entry in results}

        def _apply_page(page: dict[str, str | None], text: str) -> None:
            page_type = str(page["type"])
            if page_type not in EXPLICIT_EVIDENCE_SOURCES:
                return

            for symbol in symbols:
                snippets = self._find_snippets(text, symbol)
                evidence = results_by_symbol[symbol]["evidence"]
                migration_events = results_by_symbol[symbol]["migration_events"]
                debug_info = results_by_symbol[symbol]["_debug"]
                attempt_matches_found = 0
                debug_info["event_extraction_attempts"].append(
                    {
                        "document": self._page_title(page),
                        "url": str(page["url"]),
                        "matches_found": 0,
                    }
                )
                for snippet in snippets:
                    rejected = self._build_evidence_rejection(snippet, symbol)
                    if rejected is not None:
                        debug_info["evidence_rejected"].append(rejected)
                        continue

                    version = _extract_version(snippet, fallback=page.get("release_version"))
                    if not _is_valid_version(version):
                        events, match_records = self._build_migration_events(page, snippet, page_type)
                        debug_info["event_extraction_matches"].extend(match_records)
                        attempt_matches_found += len(match_records)
                        continue
                    evidence.append(
                        {
                            "version": version,
                            "source_type": page_type,
                            "url": str(page["url"]),
                            "matched_text": snippet,
                        }
                    )
                    events, match_records = self._build_migration_events(page, snippet, page_type)
                    migration_events.extend(events)
                    debug_info["event_extraction_matches"].extend(match_records)
                    attempt_matches_found += len(match_records)
                debug_info["event_extraction_attempts"][-1]["matches_found"] = attempt_matches_found
                if not snippets:
                    continue

                deduped_evidence: list[dict[str, Any]] = []
                seen: set[tuple[Any, ...]] = set()
                for item in sorted(
                    evidence,
                    key=lambda entry: (
                        SOURCE_PRIORITY.get(str(entry.get("source_type")), 99),
                        _version_sort_key(str(entry.get("version") or "")),
                        str(entry.get("url") or ""),
                    ),
                ):
                    key = (item.get("version"), item.get("url"), item.get("matched_text"))
                    if key in seen:
                        continue
                    seen.add(key)
                    deduped_evidence.append(item)
                    if len(deduped_evidence) >= 20:
                        break

                results_by_symbol[symbol]["evidence"] = deduped_evidence
                versions_observed = _ordered_unique_versions([item.get("version") for item in deduped_evidence])
                results_by_symbol[symbol]["versions_observed"] = versions_observed
                results_by_symbol[symbol]["earliest_version_found"] = versions_observed[0] if versions_observed else None
                results_by_symbol[symbol]["latest_version_found"] = versions_observed[-1] if versions_observed else None

                deduped_events = _dedupe_records(
                    results_by_symbol[symbol]["migration_events"],
                    lambda entry: (
                        SOURCE_PRIORITY.get(str(entry.get("source_type")), 99),
                        _version_sort_key(str(entry.get("version") or "")),
                        str(entry.get("event_type") or ""),
                        str(entry.get("title") or ""),
                        str(entry.get("url") or ""),
                    ),
                )
                results_by_symbol[symbol]["migration_events"] = deduped_events[:20]
                debug_info["event_extraction_matches"] = _dedupe_records(
                    debug_info["event_extraction_matches"],
                    lambda entry: (
                        str(entry.get("document") or ""),
                        str(entry.get("url") or ""),
                        str(entry.get("matched_text") or ""),
                        str(entry.get("event_type_detected") or ""),
                        str(entry.get("accepted") or ""),
                    ),
                )[:50]
                debug_info["evidence_rejected"] = _dedupe_records(
                    debug_info["evidence_rejected"],
                    lambda entry: (
                        str(entry.get("matched_text") or ""),
                        str(entry.get("rejection_reason") or ""),
                    ),
                )[:50]

        guide_pages = [page for page in pages if str(page["type"]) != "release_notes"]
        release_pages = [page for page in pages if str(page["type"]) == "release_notes"]

        for page in guide_pages:
            url = str(page["url"])
            text = self._fetch_page_text(url)
            if not text:
                continue

            _apply_page(page, text)

        if release_pages and any(not results_by_symbol[symbol]["versions_observed"] for symbol in symbols):
            max_workers = min(8, len(release_pages))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(self._fetch_page_text, str(page["url"])): page for page in release_pages}
                for future in as_completed(futures):
                    page = futures[future]
                    text = future.result()
                    if not text:
                        continue
                    _apply_page(page, text)

        for symbol in symbols:
            debug_info = results_by_symbol[symbol]["_debug"]
            attempts = debug_info.get("event_extraction_attempts") or []
            searched_urls = {str(item.get("url") or "") for item in attempts if item.get("url")}
            accepted_urls = {
                str(item.get("url") or "")
                for item in debug_info.get("event_extraction_matches") or []
                if item.get("accepted") and item.get("url")
            }
            debug_info["migration_documents_searched"] = len(searched_urls)
            debug_info["migration_documents_used"] = len(accepted_urls)

        return results