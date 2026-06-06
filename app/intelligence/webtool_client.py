import asyncio
import os
import httpx
from typing import Dict, List, Any
from collections import defaultdict
from app.utils.logger import get_logger

logger = get_logger(__name__)

class CircuitBreakerOpenException(Exception):
    pass

class WebtoolClient:
    def __init__(self, base_url: str = None, api_key: str = None):
        self.base_url = base_url or os.getenv("WEBTOOL_API_URL", "https://restrictedwebtool.onrender.com")
        self.api_key = api_key or os.getenv("INTERNAL_API_KEY", "vT5X3du/efIgYBGtXSC1B++jlF/7vszfSl6EtcE/wzLIQgjLZ7qyvtamNE7ZhqxI")
        
        # Connection pooling config
        limits = httpx.Limits(max_keepalive_connections=20, max_connections=100)
        timeout = httpx.Timeout(10.0, connect=5.0)
        
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"X-API-Key": self.api_key},
            limits=limits,
            timeout=timeout,
        )
        
        # Circuit Breaker state
        self.failure_count = 0
        self.failure_threshold = 5
        self.circuit_open = False
        self.last_failure_time = 0
        self.reset_timeout = 60 # seconds
        
        # Batching state
        self._batch_queue = defaultdict(list)
        self._batch_lock = asyncio.Lock()

    async def _check_circuit(self):
        if self.circuit_open:
            if asyncio.get_event_loop().time() - self.last_failure_time > self.reset_timeout:
                logger.info("Circuit breaker half-open, trying request")
                self.circuit_open = False
            else:
                raise CircuitBreakerOpenException("Circuit breaker is OPEN")

    def _record_success(self):
        self.failure_count = 0
        self.circuit_open = False

    def _record_failure(self):
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            logger.error("Circuit breaker OPENED")
            self.circuit_open = True
            self.last_failure_time = asyncio.get_event_loop().time()

    async def _request_with_retry(self, method: str, endpoint: str, **kwargs):
        max_retries = 3
        base_delay = 1.0
        
        for attempt in range(max_retries):
            await self._check_circuit()
            
            try:
                response = await self.client.request(method, endpoint, **kwargs)
                response.raise_for_status()
                self._record_success()
                return response.json()
                
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                self._record_failure()
                
                # Don't retry client errors
                if isinstance(e, httpx.HTTPStatusError) and 400 <= e.response.status_code < 500:
                    logger.error(f"Client error on {endpoint}: {e}")
                    raise
                    
                if attempt == max_retries - 1:
                    logger.error(f"Max retries reached for {endpoint}: {e}")
                    raise
                    
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Request failed, retrying in {delay}s: {e}")
                await asyncio.sleep(delay)
                
    async def get_library_intelligence(self, library: str, version: str) -> Dict[str, Any]:
        """Fetch intelligence for a specific library version."""
        endpoint = f"/api/v1/intelligence/library/{library}"
        params = {"version": version} if version and version != "unknown" else {}
        return await self._request_with_retry("GET", endpoint, params=params)
        
    async def queue_for_batch(self, library: str, symbol: str):
        """Add a symbol to the batch queue for a library."""
        async with self._batch_lock:
            self._batch_queue[library].append(symbol)
            
    async def process_batch(self) -> Dict[str, Any]:
        """Send all batched symbols and clear the queue."""
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
        
    async def close(self):
        await self.client.aclose()
