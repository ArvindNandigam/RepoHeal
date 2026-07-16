import asyncio
import json
import os
import httpx
from typing import Dict, List, Any, Callable, Optional
from collections import defaultdict
from app.cache.cache_manager import CacheManager
from app.utils.logger import get_logger

logger = get_logger(__name__)

class CircuitBreakerOpenException(Exception):
    pass

class JobCancelledException(Exception):
    pass

class WebtoolClient:
    _failure_count = 0
    _failure_threshold = 5
    _circuit_open = False
    _last_failure_time = 0.0
    _reset_timeout = 300
    _inflight: Dict[str, asyncio.Task] = {}
    _inflight_lock = asyncio.Lock()
    cancel_check = None  # Optional callable, checked during retry sleeps

    def __init__(self, base_url: str = None, api_key: str = None):
        self.base_url = base_url or os.getenv("WEBTOOL_API_URL", "https://restrictedwebtool.onrender.com")
        self.api_key = api_key or os.getenv("INTERNAL_API_KEY", "vT5X3du/efIgYBGtXSC1B++jlF/7vszfSl6EtcE/wzLIQgjLZ7qyvtamNE7ZhqxI")
        
        # Connection pooling config
        limits = httpx.Limits(max_keepalive_connections=20, max_connections=100)
        timeout = httpx.Timeout(300.0, connect=30.0)
        
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "X-API-Key": self.api_key,
            },
            limits=limits,
            timeout=timeout,
        )
        
        # Batching state
        self._batch_queue = defaultdict(list)
        self._batch_lock = asyncio.Lock()

    async def _check_circuit(self):
        if self.__class__._circuit_open:
            if asyncio.get_event_loop().time() - self.__class__._last_failure_time > self.__class__._reset_timeout:
                logger.info("Circuit breaker half-open, trying request")
                self.__class__._circuit_open = False
            else:
                raise CircuitBreakerOpenException("Circuit breaker is OPEN")

    def _record_success(self):
        self.__class__._failure_count = 0
        self.__class__._circuit_open = False

    def _record_failure(self):
        self.__class__._failure_count += 1
        if self.__class__._failure_count >= self.__class__._failure_threshold:
            logger.error("Circuit breaker OPENED")
            self.__class__._circuit_open = True
            self.__class__._last_failure_time = asyncio.get_event_loop().time()

    def _cache_key(self, method: str, endpoint: str, kwargs: Dict[str, Any]) -> str:
        payload = json.dumps(
            {
                "method": method.upper(),
                "endpoint": endpoint,
                "params": kwargs.get("params"),
                "json": kwargs.get("json"),
            },
            sort_keys=True,
            default=str
        )
        return f"webtool:{payload}"

    async def _coalesce_request(self, key: str, request_factory):
        async with self.__class__._inflight_lock:
            existing = self.__class__._inflight.get(key)
            if existing:
                logger.info(f"Coalescing duplicate Restricted Webtool request: {key}")
                task = existing
                created = False
            else:
                task = asyncio.create_task(request_factory())
                self.__class__._inflight[key] = task
                created = True

        if not created:
            return await task

        try:
            return await task
        finally:
            async with self.__class__._inflight_lock:
                if self.__class__._inflight.get(key) is task:
                    self.__class__._inflight.pop(key, None)

    async def _request_with_retry(self, method: str, endpoint: str, **kwargs):
        self._check_cancelled()
        cache_key = self._cache_key(method, endpoint, kwargs)
        cached = CacheManager.get(cache_key)
        if cached is not None:
            return cached

        async def outbound():
            result = await self._request_uncached(method, endpoint, **kwargs)
            CacheManager.set(cache_key, result, ttl_seconds=86400)
            return result

        return await self._coalesce_request(cache_key, outbound)

    async def _request_fresh(self, method: str, endpoint: str, **kwargs):
        """Same retry logic but bypasses CacheManager — always hits the webtool."""
        async def outbound():
            return await self._request_uncached(method, endpoint, **kwargs)
        cache_key = f"fresh:{method}:{endpoint}:{json.dumps(kwargs, sort_keys=True, default=str)}"
        return await self._coalesce_request(cache_key, outbound)

    def _check_cancelled(self):
        if self.__class__.cancel_check and self.__class__.cancel_check():
            raise JobCancelledException("Job was cancelled during request")

    async def _request_uncached(self, method: str, endpoint: str, **kwargs):
        delays = [2, 4, 8, 16, 32, 60, 90, 120, 120, 120]

        for attempt in range(len(delays) + 1):
            self._check_cancelled()
            await self._check_circuit()
            
            try:
                response = await self.client.request(method, endpoint, **kwargs)
                response.raise_for_status()
                self._record_success()
                return response.json()
                
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                is_429 = (
                    isinstance(e, httpx.HTTPStatusError)
                    and (e.response.status_code == 429 or "429" in str(e))
                )
                if is_429 and attempt < len(delays):
                    retry_after = e.response.headers.get("Retry-After")
                    try:
                        delay = max(float(retry_after), delays[attempt])
                    except (TypeError, ValueError):
                        delay = delays[attempt]
                    logger.warning(
                        f"Rate limited on {endpoint}; retrying in {delay}s"
                    )
                    await self._sleep_with_cancel(delay)
                    continue

                self._record_failure()

                # Don't retry other client errors.
                if isinstance(e, httpx.HTTPStatusError) and 400 <= e.response.status_code < 500:
                    logger.error(f"Client error on {endpoint}: {e}")
                    raise
                    
                if attempt == len(delays):
                    logger.error(f"Max retries reached for {endpoint}: {e}")
                    raise
                    
                delay = delays[attempt]
                logger.warning(f"Request failed, retrying in {delay}s: {e}")
                await self._sleep_with_cancel(delay)

    async def _sleep_with_cancel(self, delay: float):
        """Sleep in 1s intervals, checking cancellation between each."""
        for _ in range(int(delay)):
            self._check_cancelled()
            await asyncio.sleep(1)
        remaining = delay - int(delay)
        if remaining > 0:
            await asyncio.sleep(remaining)
                
    async def get_library_intelligence(self, library: str, version: str) -> Dict[str, Any]:
        """Fetch intelligence for a specific library version."""
        endpoint = f"/api/v1/intelligence/library/{library}"
        params = {"version": version} if version and version != "unknown" else {}
        return await self._request_with_retry("GET", endpoint, params=params)
        
    async def queue_for_batch(self, library: str, symbol: str):
        """Add a symbol to the batch queue for a library. (Deprecated: use get_bulk_intelligence)"""
        async with self._batch_lock:
            self._batch_queue[library].append(symbol)
            
    async def process_batch(self) -> Dict[str, Any]:
        """Send all batched symbols and clear the queue. (Deprecated: use get_bulk_intelligence)"""
        async with self._batch_lock:
            if not self._batch_queue:
                return {}
                
            payload = {
                "libraries": [
                    {"name": lib, "symbols": list(set(symbols))}
                    for lib, symbols in self._batch_queue.items()
                ]
            }
            self._batch_queue.clear()
            
        endpoint = "/api/v1/intelligence/batch/symbols"
        return await self._request_with_retry("POST", endpoint, json=payload)
        
    async def get_symbol_intelligence(self, library: str, symbols: List[str]) -> Dict[str, Any]:
        """Fetch intelligence for specific symbols in a library (no cache — always hits the webtool)."""
        endpoint = "/symbol-intelligence"
        payload = {"library": library, "symbols": symbols}
        return await self._request_fresh("POST", endpoint, json=payload)

    async def get_bulk_intelligence(self, libraries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Fetch intelligence for multiple libraries and symbols (no cache — always hits the webtool).
        Expected format for libraries: [{"library": "flask", "symbols": ["Flask.before_request"]}]
        """
        endpoint = "/bulk-library-intelligence"
        payload = {"libraries": libraries}
        return await self._request_fresh("POST", endpoint, json=payload)

    async def close(self):
        await self.client.aclose()
