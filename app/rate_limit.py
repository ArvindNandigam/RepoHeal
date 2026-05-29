from __future__ import annotations

from slowapi import Limiter


def _rate_limit_key(request: object) -> str:
    api_key_hash = getattr(getattr(request, "state", object()), "api_key_hash", None)
    if api_key_hash:
        return str(api_key_hash)

    client = getattr(request, "client", None)
    if client and getattr(client, "host", None):
        return str(client.host)

    return "anonymous"


limiter = Limiter(key_func=_rate_limit_key, default_limits=[], storage_uri="memory://")
