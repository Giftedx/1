import time
import asyncio
from typing import Dict, Optional
from dataclasses import dataclass
from src.metrics import METRICS

@dataclass
class RateLimit:
    max_requests: int
    time_window: float
    requests: int = 0
    window_start: float = time.time()

class RateLimiter:
    def __init__(self):
        self._limits: Dict[str, RateLimit] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, key: str, max_requests: int, time_window: float) -> bool:
        async with self._lock:
            limit = self._limits.get(key)
            if not limit:
                limit = RateLimit(max_requests, time_window)
                self._limits[key] = limit

            current_time = time.time()
            if current_time - limit.window_start > limit.time_window:
                limit.requests = 0
                limit.window_start = current_time

            if limit.requests >= limit.max_requests:
                METRICS.increment('rate_limit_hits')
                return False

            limit.requests += 1
            return True

    async def wait_for_token(self, key: str, max_requests: int, time_window: float) -> None:
        while not await self.acquire(key, max_requests, time_window):
            wait_time = self._get_wait_time(key)
            METRICS.increment('rate_limit_delays')
            await asyncio.sleep(wait_time)

    def _get_wait_time(self, key: str) -> float:
        limit = self._limits.get(key)
        if not limit:
            return 0
        return max(0, limit.window_start + limit.time_window - time.time())
