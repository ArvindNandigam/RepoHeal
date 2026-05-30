from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

from app.validators.sources import is_approved_source_url


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
    if parts:
        candidates.append(parts[-1])
    if len(parts) >= 3:
        candidates.append(parts[-3])

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _snippet(text: str, start: int, length: int, window: int = 140) -> str:
    snippet_start = max(0, start - window)
    snippet_end = min(len(text), start + length + window)
    return _normalize_whitespace(text[snippet_start:snippet_end])


def _extract_replacement_symbol(snippet: str) -> str | None:
    patterns = [
        r"renamed\s+to\s+([A-Za-z0-9_.]+)",
        r"replaced\s+by\s+([A-Za-z0-9_.]+)",
        r"use\s+([A-Za-z0-9_.]+)\s+instead",
        r"migrate\s+to\s+([A-Za-z0-9_.]+)",
        r"switch\s+to\s+([A-Za-z0-9_.]+)",
    ]
    lowered = snippet.lower()
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            return match.group(1).rstrip(".,:)[]")
    return None


def _extract_version_hint(snippet: str) -> str | None:
    patterns = [
        r"(?:introduced|added|deprecated|removed|renamed|available|released|since|in)\s+(?:version\s+)?v?(\d+(?:\.\d+){0,3}(?:[a-z0-9.-]+)?)",
        r"v?(\d+(?:\.\d+){1,3})",
    ]
    for pattern in patterns:
        match = re.search(pattern, snippet, flags=re.IGNORECASE)
        if match:
            return match.group(1).rstrip(".,;:)[]")
    return None


def _classify_snippet(source_kind: str, symbol: str, snippet: str, release_version: str | None = None) -> tuple[str, str | None, str | None, str | None, float]:
    lowered = snippet.lower()
    lifecycle = "inferred"
    if "renamed" in lowered:
        lifecycle = "renamed"
    elif "removed" in lowered or "no longer" in lowered:
        lifecycle = "removed"
    elif "replaced" in lowered or ("use " in lowered and " instead" in lowered):
        lifecycle = "replacement"
    elif "deprecated" in lowered:
        lifecycle = "deprecated"
    elif any(token in lowered for token in ("introduced", "added", "new")):
        lifecycle = "introduced"

    version_hint = _extract_version_hint(snippet)
    if version_hint is None and release_version and source_kind in {"release_notes", "changelog"} and lifecycle != "inferred":
        version_hint = release_version

    replacement_symbol = _extract_replacement_symbol(snippet)

    confidence = 0.5
    if source_kind == "migration_guide" and lifecycle != "inferred":
        confidence = 1.0
    elif source_kind in {"release_notes", "changelog"} and lifecycle != "inferred":
        confidence = 0.7

    if source_kind == "api_reference" and lifecycle != "inferred":
        confidence = max(confidence, 0.9)

    return lifecycle, version_hint, replacement_symbol, None, confidence


def _lifecycle_priority(lifecycle: str) -> int:
    priorities = {
        "removed": 4,
        "deprecated": 3,
        "renamed": 3,
        "replacement": 3,
        "introduced": 2,
        "inferred": 0,
    }
    return priorities.get(lifecycle, 0)


class SymbolEvidenceResolver:
    def __init__(self, source_resolver: Any) -> None:
        self.source_resolver = source_resolver

    def _build_pages(self, source_bundle: dict[str, Any]) -> list[dict[str, str | None]]:
        pages: list[dict[str, str | None]] = []
        source_contract = source_bundle["source_contract"]
        pages.append({"type": "api_reference", "url": source_contract["official_docs"], "release_version": None})
        pages.append({"type": "github_repo", "url": source_contract["github_repo"], "release_version": None})

        for entry in source_bundle.get("release_history", []):
            pages.append({"type": "release_notes", "url": entry["url"], "release_version": entry.get("version")})

        for guide in source_bundle.get("migration_guides", []):
            title = guide.get("title", "").lower()
            guide_type = "changelog" if "changelog" in title else "migration_guide"
            if "release notes" in title:
                guide_type = "release_notes"
            elif any(token in title for token in ("api reference", "reference", "api docs")):
                guide_type = "api_reference"
            pages.append({"type": guide_type, "url": guide["url"], "release_version": None})

        seen: set[str] = set()
        deduped: list[dict[str, str | None]] = []
        for page in pages:
            url = str(page["url"])
            if url in seen:
                continue
            seen.add(url)
            deduped.append(page)
        return deduped

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
                snippets.append(_snippet(text, index, len(candidate)))
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
        page_texts: list[dict[str, Any]] = []

        for page in pages:
            url = str(page["url"])
            text = self._fetch_page_text(url)
            if text:
                page_texts.append({**page, "text": text})

        results: list[dict[str, Any]] = []
        for symbol in symbols:
            evidence: list[dict[str, str]] = []
            lifecycle = "inferred"
            lifecycle_score = 0
            introduced_version = None
            deprecated_version = None
            removed_version = None
            replacement_symbol = None
            evidence_types: set[str] = set()

            for page in page_texts:
                page_type = str(page["type"])
                release_version = page.get("release_version")
                snippets = self._find_snippets(str(page["text"]), symbol)
                for snippet in snippets:
                    lifecycle_hint, version_hint, replacement_hint, _, _ = _classify_snippet(
                        page_type,
                        symbol,
                        snippet,
                        release_version=str(release_version) if release_version else None,
                    )
                    hint_score = _lifecycle_priority(lifecycle_hint)
                    if hint_score > lifecycle_score:
                        lifecycle = lifecycle_hint
                        lifecycle_score = hint_score
                    if lifecycle_hint == "introduced" and introduced_version is None:
                        introduced_version = version_hint or (str(release_version) if release_version else None)
                    if lifecycle_hint == "deprecated" and deprecated_version is None:
                        deprecated_version = version_hint or (str(release_version) if release_version else None)
                    if lifecycle_hint == "removed" and removed_version is None:
                        removed_version = version_hint or (str(release_version) if release_version else None)
                    if lifecycle_hint in {"renamed", "replacement"} and replacement_symbol is None:
                        replacement_symbol = replacement_hint

                    evidence.append({"type": page_type, "url": str(page["url"]), "matched_text": snippet})
                    evidence_types.add(page_type)

            if not evidence:
                evidence = [{"type": "fallback", "url": source_bundle["source_contract"]["official_docs"], "matched_text": symbol}]

            confidence = 0.5
            if "migration_guide" in evidence_types and lifecycle != "inferred":
                confidence = 1.0
            elif {"api_reference", "changelog"}.issubset(evidence_types) or {"api_reference", "release_notes"}.issubset(evidence_types):
                confidence = 0.9
            elif evidence_types.intersection({"release_notes", "changelog"}):
                confidence = 0.7

            if lifecycle == "inferred" and evidence_types:
                confidence = 0.5

            results.append(
                {
                    "symbol": symbol,
                    "lifecycle": lifecycle,
                    "introduced_version": introduced_version,
                    "deprecated_version": deprecated_version,
                    "removed_version": removed_version,
                    "replacement_symbol": replacement_symbol,
                    "confidence": confidence,
                    "evidence": evidence,
                }
            )

        return results