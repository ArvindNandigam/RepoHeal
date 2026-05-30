from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin
from urllib.parse import urlparse

import httpx

from app.config import get_settings
from app.observability.repository import OperationalRepository
from app.validators.sources import is_approved_source_url, validate_source_urls


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attr_map = {key: value for key, value in attrs if value}
        href = attr_map.get("href")
        text = attr_map.get("title") or href or ""
        if href:
            self.links.append((text, href))


class CircuitBreakerOpenError(RuntimeError):
    pass


class LibraryNotFoundError(RuntimeError):
    pass


class SourceUnavailableError(RuntimeError):
    pass


def _pick_project_url(project_urls: dict[str, str], preferred_labels: set[str]) -> str | None:
    for label, url in project_urls.items():
        if label.strip().lower() in preferred_labels:
            return url
    return None


def _is_real_github_repo_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc.lower() != "github.com":
        return False

    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) < 2:
        return False

    blocked_roots = {
        "about",
        "blog",
        "collections",
        "contact",
        "explore",
        "features",
        "login",
        "new",
        "notifications",
        "orgs",
        "pricing",
        "pull",
        "pulls",
        "search",
        "sessions",
        "site",
        "sponsors",
        "topics",
        "trending",
    }
    return path_parts[0] not in blocked_roots


def _extract_github_repo(project_urls: dict[str, str], home_page: str | None) -> str:
    candidates: list[str] = []

    for label, url in project_urls.items():
        label_clean = label.strip().lower()
        if any(token in label_clean for token in ("source", "github", "repo", "repository", "code")):
            candidates.append(url)

    if home_page:
        candidates.append(home_page)

    candidates.extend(project_urls.values())

    for candidate in candidates:
        if _is_real_github_repo_url(candidate):
            return candidate.rstrip("/")
    raise SourceUnavailableError("Official GitHub repository not found")


def _extract_official_docs(project_urls: dict[str, str], home_page: str | None) -> str:
    docs_url = _pick_project_url(project_urls, {"documentation", "docs"})
    if docs_url:
        return docs_url.rstrip("/")

    if home_page and ("docs." in home_page or "readthedocs" in home_page):
        return home_page.rstrip("/")

    for url in project_urls.values():
        if "docs." in url or "readthedocs" in url:
            return url.rstrip("/")

    raise ValueError("Official documentation URL not found")


def _extract_migration_guides(project_urls: dict[str, str]) -> list[dict[str, str]]:
    guides: list[dict[str, str]] = []
    for label, url in project_urls.items():
        label_clean = label.strip().lower()
        if any(token in label_clean for token in ("migration", "upgrade", "changelog", "release notes")):
            guides.append({"title": label.strip(), "url": url.rstrip("/")})
    return guides


def _dedupe_migration_guides(guides: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for guide in guides:
        key = guide["url"].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(guide)
    return deduped


def _extract_release_history(releases: dict[str, list[dict[str, Any]]], base_url: str) -> list[dict[str, Any]]:
    release_entries: list[tuple[str, str | None, str]] = []
    for version, files in releases.items():
        if not files:
            continue
        best_file = max(
            files,
            key=lambda item: item.get("upload_time_iso_8601") or item.get("upload_time") or "",
        )
        published_at = best_file.get("upload_time_iso_8601") or best_file.get("upload_time")
        release_entries.append((version, published_at, f"{base_url}/releases/tag/v{version}"))

    release_entries.sort(key=lambda item: item[1] or "", reverse=True)
    return [{"version": version, "url": url, "published_at": published_at} for version, published_at, url in release_entries[:10]]


def _fetch_url(client: httpx.Client, url: str) -> str:
    response = client.get(url, follow_redirects=True)
    response.raise_for_status()
    return response.text


def _discover_guide_links(fetch_page, docs_url: str, extra_domains: list[str] | None = None) -> list[dict[str, str]]:
    discovered: list[dict[str, str]] = []
    try:
        html = fetch_page(docs_url).text
    except Exception:
        return discovered

    parser = _LinkParser()
    parser.feed(html)
    for title, href in parser.links:
        title_clean = title.strip().lower()
        if any(token in title_clean for token in ("migration", "upgrade", "changelog", "release notes")):
            guide_url = urljoin(docs_url, href)
            if not is_approved_source_url(guide_url, extra_domains=extra_domains):
                continue
            discovered.append({"title": title.strip() or href, "url": guide_url})
    return discovered


def _fallback_symbol_lifecycle(symbol: str, bundle: dict[str, Any]) -> dict[str, Any]:
    known_replacements = {
        "openai.chatcompletion.create": "client.chat.completions.create",
    }

    replacement = known_replacements.get(symbol.strip().lower())
    lifecycle = "removed" if replacement else "inferred"
    return {
        "symbol": symbol,
        "lifecycle": lifecycle,
        "introduced_version": None,
        "deprecated_version": None,
        "removed_version": None,
        "replacement_symbol": replacement,
        "confidence": 0.5,
        "evidence": [
            {
                "type": "fallback",
                "url": bundle["source_contract"]["official_docs"],
                "matched_text": symbol,
            }
        ],
    }


class OfficialSourceResolver:
    def __init__(self, operational_repository: OperationalRepository, timeout_seconds: float | None = None, retry_count: int | None = None) -> None:
        settings = get_settings()
        self.operational_repository = operational_repository
        self.timeout = httpx.Timeout(timeout_seconds or settings.upstream_timeout_seconds)
        self.retry_count = retry_count or settings.upstream_retry_count
        self.client = httpx.Client(timeout=self.timeout, headers={"User-Agent": "RestrictedWebTool/1.0"})

    def close(self) -> None:
        self.client.close()

    def _get_github_status(self) -> dict[str, Any] | None:
        return self.operational_repository.get_service_status("github")

    def _is_github_degraded(self) -> bool:
        status = self._get_github_status()
        if not status:
            return False
        if status.get("status") != "degraded":
            return False
        retry_after = status.get("retry_after")
        if retry_after is None:
            return False
        if isinstance(retry_after, str):
            retry_after = datetime.fromisoformat(retry_after)
        if retry_after.tzinfo is None:
            retry_after = retry_after.replace(tzinfo=timezone.utc)
        return retry_after > datetime.now(timezone.utc)

    def _mark_github_degraded(self, retry_after: datetime) -> None:
        self.operational_repository.mark_service_status("github", "degraded", retry_after=retry_after)

    def _mark_github_healthy(self) -> None:
        self.operational_repository.mark_service_status("github", "healthy", retry_after=None)

    def resolve_sources(self, library: str, trust_sources: bool = False) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, str]], dict[str, Any]]:
        pypi_url = f"https://pypi.org/pypi/{library}/json"
        response = self._request_with_retries(pypi_url)
        pypi_json = response.json()

        info = pypi_json["info"]
        project_urls = dict(info.get("project_urls") or {})
        home_page = info.get("home_page")
        github_repo = _extract_github_repo(project_urls, home_page)
        latest_version = info["version"]

        try:
            official_docs = _extract_official_docs(project_urls, home_page)
        except ValueError:
            official_docs = github_repo

        if trust_sources:
            source_contract = {
                "library": library,
                "official_docs": official_docs,
                "github_repo": github_repo,
                "pypi_url": pypi_url,
                "latest_version": latest_version,
            }
        else:
            from app.validators.sources import validate_source_urls as _validate_source_urls

            _validate_source_urls([official_docs, github_repo, pypi_url])
            source_contract = {
                "library": library,
                "official_docs": official_docs,
                "github_repo": github_repo,
                "pypi_url": pypi_url,
                "latest_version": latest_version,
            }

        release_history = _extract_release_history(pypi_json.get("releases", {}), github_repo)
        migration_guides = _extract_migration_guides(project_urls)

        verified_hosts: list[str] = []
        try:
            from urllib.parse import urlparse as _urlparse

            if official_docs:
                parsed = _urlparse(official_docs)
                if parsed.hostname:
                    verified_hosts.append(parsed.hostname)
            if github_repo:
                parsed = _urlparse(github_repo)
                if parsed.hostname:
                    verified_hosts.append(parsed.hostname)
        except Exception:
            verified_hosts = []

        migration_guides.extend(_discover_guide_links(self._request_with_retries, official_docs, extra_domains=verified_hosts))
        migration_guides = _dedupe_migration_guides(migration_guides)
        if not trust_sources:
            validate_source_urls([guide["url"] for guide in migration_guides], extra_domains=verified_hosts)

        return source_contract, release_history, migration_guides, pypi_json

    def _request_with_retries(self, url: str) -> httpx.Response:
        is_github_url = "github.com" in url.lower()
        if is_github_url and self._is_github_degraded():
            raise CircuitBreakerOpenError("github circuit open")

        last_error: Exception | None = None
        for attempt in range(self.retry_count):
            try:
                response = self.client.get(url, follow_redirects=True)
                if response.status_code == 429 and is_github_url:
                    retry_after_header = response.headers.get("Retry-After")
                    if retry_after_header and retry_after_header.isdigit():
                        retry_after = datetime.now(timezone.utc) + timedelta(seconds=int(retry_after_header))
                    else:
                        retry_after = datetime.now(timezone.utc) + timedelta(minutes=10)
                    if attempt >= self.retry_count - 1:
                        self._mark_github_degraded(retry_after)
                        raise CircuitBreakerOpenError("github rate limited")
                    last_error = CircuitBreakerOpenError("github rate limited")
                else:
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        if "pypi.org/pypi/" in url and exc.response.status_code == 404:
                            raise LibraryNotFoundError(url) from exc
                        raise SourceUnavailableError(url) from exc
                    if is_github_url:
                        self._mark_github_healthy()
                    return response
            except (httpx.HTTPError, CircuitBreakerOpenError, LibraryNotFoundError, SourceUnavailableError) as exc:
                last_error = exc
                if attempt >= self.retry_count - 1:
                    break
                backoff_seconds = 0.25 * (2 ** attempt)
                if is_github_url:
                    backoff_seconds = min(backoff_seconds, 1.0)
                import time

                time.sleep(backoff_seconds)

        assert last_error is not None
        raise last_error

    def resolve(self, library: str, symbols: list[str], trust_sources: bool = False) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]], dict[str, Any]]:
        source_contract, release_history, migration_guides, pypi_json = self.resolve_sources(library, trust_sources=trust_sources)

        from app.services.symbol_evidence_resolver import SymbolEvidenceResolver

        resolver = SymbolEvidenceResolver(self)
        bundle = {
            "source_contract": source_contract,
            "release_history": release_history,
            "migration_guides": migration_guides,
            "pypi_json": pypi_json,
        }
        symbol_lifecycles = resolver.resolve_from_source_bundle(library, symbols, bundle)

        if len(symbol_lifecycles) != len(symbols):
            resolved_symbols = {item["symbol"] for item in symbol_lifecycles}
            for symbol in symbols:
                if symbol not in resolved_symbols:
                    symbol_lifecycles.append(_fallback_symbol_lifecycle(symbol, bundle))

        return source_contract, symbol_lifecycles, release_history, migration_guides, pypi_json
