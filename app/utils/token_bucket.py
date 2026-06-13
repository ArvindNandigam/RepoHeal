import asyncio
import time
from typing import List, Tuple

from app.utils.logger import get_logger

logger = get_logger(__name__)


class TokenBucket:
    """Sliding-window token/request bucket for API rate limiting.

    Tracks both tokens-per-minute and requests-per-minute.  Blocks the
    caller when either limit is reached until the oldest request falls
    outside the window.
    """

    def __init__(
        self,
        max_tokens_per_minute: int = 12000,
        max_requests_per_minute: int = 30,
        max_requests_per_day: int = 1440,
    ):
        self.max_tpm = max_tokens_per_minute
        self.max_rpm = max_requests_per_minute
        self.max_rpd = max_requests_per_day
        self._window_seconds = 60
        self._day_seconds = 86400
        self._records: List[Tuple[float, int]] = []  # (timestamp, tokens_used)
        self._lock = asyncio.Lock()

    async def acquire(self, estimated_tokens: int = 0) -> None:
        """Wait until capacity is available, then record an entry.

        *estimated_tokens* is used before the actual request; the caller
        should later call *record_actual()* to correct the token count.
        """
        async with self._lock:
            await self._wait_for_capacity(estimated_tokens)
            self._records.append((time.time(), estimated_tokens))

    async def record_actual(self, actual_tokens: int) -> None:
        """Replace the most-recent entry's token count with the real value."""
        async with self._lock:
            if self._records:
                self._records[-1] = (self._records[-1][0], actual_tokens)

    async def _wait_for_capacity(self, estimated_tokens: int) -> None:
        now = time.time()
        cutoff_60 = now - self._window_seconds
        cutoff_day = now - self._day_seconds

        # Prune expired entries
        self._records = [(ts, t) for ts, t in self._records if ts > cutoff_60]

        # Check daily limit
        day_records = [(ts, t) for ts, t in self._records if ts > cutoff_day]
        if len(day_records) >= self.max_rpd:
            oldest_day = min(ts for ts, _ in day_records)
            wait = oldest_day + self._day_seconds - now
            if wait > 0:
                logger.info(f"Daily request limit reached — sleeping {wait:.0f}s")
                self._records = []  # Clear (will be re-acquired after sleep)
                await asyncio.sleep(wait)
                now = time.time()
                cutoff_60 = now - self._window_seconds
                self._records = [(ts, t) for ts, t in self._records if ts > cutoff_60]

        current_tokens = sum(t for _, t in self._records)
        current_reqs = len(self._records)

        if current_tokens >= self.max_tpm or current_reqs >= self.max_rpm:
            oldest = min(ts for ts, _ in self._records)
            wait = oldest + self._window_seconds - now
            if wait > 0:
                logger.info(
                    f"Rate limit reached "
                    f"({current_tokens}/{self.max_tpm} tokens, "
                    f"{current_reqs}/{self.max_rpm} reqs in window) — "
                    f"sleeping {wait:.1f}s"
                )
                self._records = []
                await asyncio.sleep(wait)
                now = time.time()
                cutoff_60 = now - self._window_seconds
                self._records = [(ts, t) for ts, t in self._records if ts > cutoff_60]


# Shared singleton used by all Groq/LLM callers
groq_bucket = TokenBucket()
