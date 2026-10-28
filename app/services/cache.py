from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import Any


@dataclass(frozen=True)
class CacheEntry:
    value: dict[str, Any]
    expires_at: float


class IntelligenceCache:
    def __init__(self, positive_ttl_seconds: float, negative_ttl_seconds: float) -> None:
        self.positive_ttl_seconds = positive_ttl_seconds
        self.negative_ttl_seconds = negative_ttl_seconds
        self._positive: dict[tuple[str, tuple[str, ...]], CacheEntry] = {}
        self._negative: dict[tuple[str, tuple[str, ...]], CacheEntry] = {}
        self._lock = RLock()

    def get(self, library: str, symbols: list[str]) -> tuple[dict[str, Any] | None, str | None]:
        key = (library, tuple(symbols))
        now = monotonic()
        with self._lock:
            for name, cache in (("positive", self._positive), ("negative", self._negative)):
                entry = cache.get(key)
                if entry is None:
                    continue
                if entry.expires_at <= now:
                    cache.pop(key, None)
                    continue
                return deepcopy(entry.value), name
        return None, None

    def put(self, library: str, symbols: list[str], value: dict[str, Any], positive: bool) -> None:
        key = (library, tuple(symbols))
        entry = CacheEntry(
            value=deepcopy(value),
            expires_at=monotonic() + (self.positive_ttl_seconds if positive else self.negative_ttl_seconds),
        )
        with self._lock:
            (self._positive if positive else self._negative)[key] = entry

    def clear(self) -> None:
        with self._lock:
            self._positive.clear()
            self._negative.clear()
