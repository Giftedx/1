import asyncio
import logging
from typing import Optional, Any, Dict, List, Tuple, AsyncGenerator
import aioredis
from prometheus_client import Gauge, Histogram
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

REDIS_POOL_USAGE = Gauge('redis_pool_connections', 'Number of active Redis connections')
REDIS_HEALTH = Gauge('redis_health', 'Redis connection health status')

class RedisManager:
    def __init__(self, url: str, pool_size: int = 10):
        self.url = url
        self.pool_size = pool_size
        self._pool: Optional[aioredis.Redis] = None  # Use aioredis.Redis type
        self._reconnect_delay = 1.0
        self.redis: Optional[aioredis.Redis] = None
        self._closed = False
        self._health_check_task: Optional[asyncio.Task] = None
        self._metrics: Dict[str, float] = {}
        self._connection_retries = 0
        self._max_connection_retries = 5
        self._connection_timeout = 30.0
        self._operation_latency = Histogram(
            'redis_operation_latency_seconds',
            'Redis operation latency in seconds',
            ['operation']
        )
        self._connection_pool_semaphore = asyncio.Semaphore(pool_size)

    @classmethod
    async def create(cls, url: str, pool_size: int = 10) -> "RedisManager":
        instance = cls(url, pool_size)
        await instance._connect()
        return instance

    async def _connect(self) -> None:
        try:
            self.redis = await aioredis.from_url(self.url, max_connections=self.pool_size)
            logger.info("Connected to Redis server")
            REDIS_HEALTH.set(1)  # Set health to 1 (healthy)
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}", exc_info=True)
            REDIS_HEALTH.set(0)  # Set health to 0 (unhealthy)
            raise

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[aioredis.Redis, None]:
        """Context manager for acquiring and releasing a Redis connection."""
        try:
            async with self._connection_pool_semaphore:
                yield self.redis
        except Exception as e:
            logger.error(f"Error acquiring Redis connection: {e}", exc_info=True)
            raise
        finally:
            pass  # No need to explicitly release, aioredis handles it

    async def execute(self, command: str, *args: Any, **kwargs: Any) -> Any:
        """Execute a Redis command with error handling and metrics."""
        try:
            async with self.connection() as redis:
                with self._operation_latency.labels(operation=command).time():
                    result = await redis.execute_command(command, *args, **kwargs)
                return result
        except Exception as e:
            logger.error(f"Redis command '{command}' failed: {e}", exc_info=True)
            raise

    async def flush_all(self):
        """Flush all data from Redis."""
        try:
            async with self.connection() as redis:
                await redis.flushall()
            logger.info("Redis flushed successfully")
        except Exception as e:
            logger.error(f"Failed to flush Redis: {e}", exc_info=True)
            raise

    async def close(self) -> None:
        """Close the Redis connection."""
        if self.redis:
            await self.redis.close()
            logger.info("Redis connection closed")
        REDIS_HEALTH.set(0)