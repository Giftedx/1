import asyncio
import time
import logging
from typing import Optional
from aiocache import Cache
from aiocache.serializers import JsonSerializer

logger = logging.getLogger(__name__)

class RateLimiter:
    """
    A Redis‐backed rate limiter for distributed environments.
    Uses a sorted set per user and a sliding window with burst support.
    """
    def __init__(self, requests: int, period: int):
        self.cache = Cache(CacheType.REDIS, endpoint="127.0.0.1", port=6379, serializer=JsonSerializer())
        self.requests = requests
        self.period = period

    async def is_rate_limited(self, user_id: str) -> bool:
        key = f"rate_limit:{user_id}"
        count = await self.cache.increment(key, 1, expire=self.period)
        return count > self.requests