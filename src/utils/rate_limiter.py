import asyncio
import time
import logging
from typing import Optional
from src.core.redis_manager import RedisManager

logger = logging.getLogger(__name__)

class RateLimiter:
    """
    A Redis‐backed rate limiter for distributed environments.
    Uses a sorted set per user and a sliding window with burst support.
    """
    def __init__(self, max_requests: int, window_seconds: int, burst_limit: int = None):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.burst_limit = burst_limit or max_requests * 2
        self.redis_manager: Optional[RedisManager] = None
        self._lock = asyncio.Lock()

    def set_redis_manager(self, redis_manager: RedisManager) -> None:
        self.redis_manager = redis_manager

    async def initialize(self) -> None:
        if not self.redis_manager:
            async with self._lock:
                self.redis_manager = await RedisManager.create()
                # Log that RedisManager was initialized
                logger.info("RedisManager initialized for RateLimiter.")

    async def is_rate_limited(self, user_id: str) -> bool:
        try:
            return await self._check_rate_limit(user_id)
        except Exception as e:
            logger.error(f"Rate limiter error for user {user_id}: {e}", exc_info=True)
            return False  # Fail open in case of errors

    async def _check_rate_limit(self, user_id: str) -> bool:
        await self.initialize()
        key = f"rl:{user_id}"
        now = int(time.time())
        try:
            async with self.redis_manager.redis.pipeline() as pipe:
                # Queue commands atomically.
                pipe.multi()
                pipe.zadd(key, {str(now): now})
                pipe.zremrangebyscore(key, 0, now - self.window_seconds)
                pipe.zcard(key)
                pipe.expire(key, self.window_seconds)
                _, _, count, _ = await pipe.execute()
            # Log current rate limit count
            logger.debug(f"User {user_id} has {count} requests in the window.")
            return count >= self.burst_limit
        except Exception as e:
            logger.error(f"Failed checking rate limit for user {user_id}: {e}", exc_info=True)
            raise

    async def reset_rate_limit(self, user_id: str) -> None:
        await self.initialize()
        key = f"rl:{user_id}"
        try:
            await self.redis_manager.redis.delete(key)
            logger.info(f"Rate limit reset for user {user_id}.")
        except Exception as e:
            logger.error(f"Error resetting rate limit for user {user_id}: {e}", exc_info=True)