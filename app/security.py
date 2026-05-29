from __future__ import annotations

import hashlib
import hmac


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


def is_bearer_token_valid(raw_token: str, allowed_hashes: list[str]) -> bool:
    token_hash = hash_api_key(raw_token)
    return any(constant_time_equals(token_hash, allowed_hash) for allowed_hash in allowed_hashes)
