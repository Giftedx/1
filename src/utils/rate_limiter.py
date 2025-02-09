import asyncio
import time
import logging
from typing import Optional
import redis.asyncio as redis

logger = logging.getLogger(__name__)

class RateLimiter:
    """
    A Redis‐backed rate limiter for distributed environments.
    Uses a sorted set per user and a sliding window with burst support.
    """
    def __init__(self, host: str = "localhost", port: int = 6379, requests: int = 10, period: int = 60):
        self.redis = redis.Redis(host=host, port=port)
        self.requests = requests
        self.period = period

    async def is_rate_limited(self, user_id: str) -> bool:
        """
        Checks if a user is rate-limited.

        Args:
            user_id: The ID of the user.

        Returns:
            True if the user is rate-limited, False otherwise.
        """
        key = f"rate_limit:{user_id}"
        now = int(time.time())

        # Remove outdated entries
        await self.redis.zremrangebyscore(key, 0, now - self.period)

        # Count entries within the time window
        count = await self.redis.zcard(key)

        if count >= self.requests:
            return True

        # Add the current request to the sorted set
        await self.redis.zadd(key, {now: now})
        await self.redis.expire(key, self.period)  # Ensure the key expires

        return False