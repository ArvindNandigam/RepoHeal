from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

from app.validators.sources import is_approved_source_url

EXPLICIT_EVIDENCE_SOURCES = {"migration_guide", "changelog", "release_notes", "official_deprecation_notice"}


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


def _evidence_relevance_score(source_kind: str) -> float:
    if source_kind in {"migration_guide", "official_deprecation_notice"}:
        return 0.95
    if source_kind == "changelog":
        return 0.9
    if source_kind == "release_notes":
        return 0.85
    return 0.0


class SymbolEvidenceResolver:
    def __init__(self, source_resolver: Any) -> None:
        self.source_resolver = source_resolver

    def _build_pages(self, source_bundle: dict[str, Any]) -> list[dict[str, str | None]]:
        pages: list[dict[str, str | None]] = []

        for entry in source_bundle.get("release_history", []):
            pages.append({"type": "release_notes", "url": entry["url"], "release_version": entry.get("version")})

        for guide in source_bundle.get("migration_guides", []):
            title = guide.get("title", "").lower()
            guide_type = "changelog" if "changelog" in title else "migration_guide"
            if "release notes" in title:
                guide_type = "release_notes"
            elif "deprecat" in title:
                guide_type = "official_deprecation_notice"
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
            evidence: list[dict[str, Any]] = []

            for page in page_texts:
                page_type = str(page["type"])
                snippets = self._find_snippets(str(page["text"]), symbol)
                for snippet in snippets:
                    if page_type not in EXPLICIT_EVIDENCE_SOURCES:
                        continue
                    evidence.append(
                        {
                            "source_type": page_type,
                            "url": str(page["url"]),
                            "matched_text": snippet,
                            "relevance_score": _evidence_relevance_score(page_type),
                        }
                    )

            deduped_evidence: list[dict[str, Any]] = []
            seen: set[tuple[Any, ...]] = set()
            for item in evidence:
                key = (item.get("source_type"), item.get("url"), item.get("matched_text"))
                if key in seen:
                    continue
                seen.add(key)
                deduped_evidence.append(item)

            results.append(
                {
                    "symbol": symbol,
                    "introduced_version": None,
                    "deprecated_version": None,
                    "removed_version": None,
                    "replacement_symbol": None,
                    "confidence": 0,
                    "evidence": deduped_evidence,
                }
            )

        return results