from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from app.config import get_settings


def _matches_allowed_domain(hostname: str, pattern: str) -> bool:
    pattern = pattern.lower().strip()
    if not pattern:
        return False
    if pattern.startswith("*."):
        suffix = pattern[1:]
        return hostname == pattern[2:] or hostname.endswith(suffix)
    return hostname == pattern or hostname.endswith(f".{pattern}")


def _is_public_ip(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False

    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped

    return not any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_reserved,
            ip.is_unspecified,
            ip.is_multicast,
            not ip.is_global,
        )
    )


def _hostname_resolves_to_public_ip(hostname: str, port: int) -> bool:
    try:
        addresses = {
            result[4][0]
            for result in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        }
    except (OSError, socket.gaierror):
        return False
    return bool(addresses) and all(_is_public_ip(address) for address in addresses)


def is_approved_source_url(url: str, extra_domains: list[str] | None = None) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.username or parsed.password:
        return False

    try:
        hostname = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except (UnicodeError, ValueError):
        return False

    allowed_domains = list(get_settings().allowed_domains)
    if extra_domains:
        # add any verified domains discovered at runtime
        allowed_domains.extend(d.strip().lower() for d in extra_domains if d)

    if not any(_matches_allowed_domain(hostname, pattern) for pattern in allowed_domains):
        return False

    return _hostname_resolves_to_public_ip(hostname, port)


def validate_source_urls(urls: list[str], extra_domains: list[str] | None = None) -> None:
    for url in urls:
        if not is_approved_source_url(url, extra_domains=extra_domains):
            raise ValueError(f"Unapproved source url: {url}")
