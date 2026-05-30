from __future__ import annotations

from urllib.parse import urlparse

from app.config import get_settings


def _matches_allowed_domain(hostname: str, pattern: str) -> bool:
    pattern = pattern.lower().strip()
    if not pattern:
        return False
    if pattern.endswith(".*"):
        return hostname.startswith(pattern[:-1])
    if pattern.startswith("*."):
        suffix = pattern[1:]
        return hostname == pattern[2:] or hostname.endswith(suffix)
    return hostname == pattern or hostname.endswith(f".{pattern}")


def is_approved_source_url(url: str, extra_domains: list[str] | None = None) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False

    hostname = parsed.hostname.lower()
    allowed_domains = list(get_settings().allowed_domains)
    if extra_domains:
        # add any verified domains discovered at runtime
        allowed_domains.extend(d.strip().lower() for d in extra_domains if d)

    return any(_matches_allowed_domain(hostname, pattern) for pattern in allowed_domains)


def validate_source_urls(urls: list[str], extra_domains: list[str] | None = None) -> None:
    for url in urls:
        if not is_approved_source_url(url, extra_domains=extra_domains):
            raise ValueError(f"Unapproved source url: {url}")
