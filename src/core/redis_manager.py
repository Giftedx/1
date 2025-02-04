import aioredis
import logging
import asyncio
from typing import Optional, Any, Dict
from prometheus_client import Gauge, Histogram
from src.core.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

REDIS_POOL_USAGE = Gauge('redis_pool_connections', 'Number of active Redis connections')
REDIS_HEALTH = Gauge('redis_health', 'Redis connection health status')

class RedisManager:
    def __init__(self, redis_url: str, pool_size: int):
        self.redis_url = redis_url
        self.pool_size = pool_size
        self.redis: Optional[aioredis.Redis] = None
        self._closed = False
        self._health_check_task: Optional[asyncio.Task] = None
        self._metrics: Dict[str, float] = {}
        self._connection_retries = 0
        self._max_connection_retries = 5
        self._connection_timeout = 30.0
        self._circuit_breaker = CircuitBreaker(failure_threshold=3)
        self._operation_latency = Histogram(
            'redis_operation_latency_seconds',
            'Redis operation latency in seconds',
            ['operation']
        )

    @classmethod
    async def create(cls, redis_url: str = "redis://localhost:6379", pool_size: int = 20, max_retries: int = 3):
        instance = cls(redis_url, pool_size)
        for attempt in range(max_retries):
            try:
                instance.redis = await aioredis.from_url(
                    redis_url,
                    max_connections=pool_size,
                    decode_responses=True
                )
                return instance
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(1)
        return instance

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        async with self._operation_latency.labels(args[0]).time():
            return await self._circuit_breaker.call(
                self._execute_with_retry, *args, **kwargs
            )

    async def _execute_with_retry(self, *args: Any, **kwargs: Any) -> Any:
        for retry in range(self._max_connection_retries):
            try:
                if self._closed:
                    raise RuntimeError("RedisManager is closed")
                return await self.redis.execute_command(*args, **kwargs)
            except (aioredis.ConnectionError, aioredis.TimeoutError) as e:
                if retry == self._max_connection_retries - 1:
                    REDIS_HEALTH.set(0)
                    raise
                await asyncio.sleep(min(2 ** retry, 10))
                continue

    async def flush_all(self):
        try:
            await self.redis.flushall()
            logger.info("Flushed all data in Redis.")
        except Exception as e:
            logger.error(f"Error flushing Redis data: {e}")

    async def _health_check(self) -> None:
        while not self._closed:
            try:
                await self.redis.ping()
                REDIS_HEALTH.set(1)
                REDIS_POOL_USAGE.set(len(self.redis.connection_pool._available_connections))
            except Exception:
                REDIS_HEALTH.set(0)
            await asyncio.sleep(30)

    async def start_health_checks(self) -> None:
        if not self._health_check_task:
            self._health_check_task = asyncio.create_task(self._health_check())

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        if self.redis:
            await self.redis.close()
            await self.redis.connection_pool.disconnect()