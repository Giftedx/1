import aioredis
import logging
import asyncio
from typing import Optional, Any, Dict, List, Tuple
from prometheus_client import Gauge, Histogram
from src.core.circuit_breaker import CircuitBreaker
import aioping
from contextlib import asynccontextmanager
from src.utils.connection_pool import AdaptiveConnectionPool

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
        self._connection_pool_semaphore = asyncio.Semaphore(pool_size)
        self._health_metrics = HealthMetrics()
        self._pool_stats = PoolStats()
        self._pool_monitor = PoolMonitor(threshold=0.8)
        self._connection_limiter = TokenBucket(rate=100, capacity=pool_size)
        self._cleanup_hook = None
        self._pool_config = PoolConfig(
            min_size=max(5, pool_size // 4),
            max_size=pool_size,
            connection_ttl=300,
            health_check_interval=30
        )
        self._connection_manager = ConnectionManager(
            config=self._pool_config,
            on_connect=self._setup_connection,
            on_disconnect=self._cleanup_connection
        )
        self._connection_pool = AdaptiveConnectionPool(
            url=redis_url,
            min_size=max(5, pool_size // 4),
            max_size=pool_size,
            idle_timeout=300,
            max_lifetime=3600,
            validation_interval=30
        )
        self._command_cache = LRUCache(
            maxsize=1000,
            ttl=60,
            on_evict=self._on_cache_evict
        )
        self._failover_strategy = FailoverStrategy(
            retries=3,
            backoff_factor=1.5
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

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[aioredis.Redis, None]:
        async with self._connection_pool.acquire() as conn:
            try:
                await self._validate_connection(conn)
                yield conn
            except Exception as e:
                await self._handle_connection_error(e)
                raise

    async def _validate_connection(self, conn: aioredis.Redis) -> bool:
        try:
            async with async_timeout.timeout(1.0):
                await conn.ping()
                return True
        except Exception as e:
            await self._handle_connection_error(conn, e)
            return False

    async def _check_connection_health(self) -> None:
        if not await aioping.ping(self.redis_url, timeout=1):
            REDIS_HEALTH.set(0)
            raise ConnectionError("Redis health check failed")

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        async with self._connection_pool_semaphore:
            async with self._operation_latency.labels(args[0]).time():
                return await self._circuit_breaker.call(
                    self._execute_with_retry, *args, **kwargs
                )

    async def _execute_with_retry(self, *args: Any, **kwargs: Any) -> Any:
        backoff = ExponentialBackoff(min_delay=0.1, max_delay=5.0)
        for retry in range(self._max_connection_retries):
            try:
                async with async_timeout.timeout(self._connection_timeout):
                    return await self.redis.execute_command(*args, **kwargs)
            except (aioredis.ConnectionError, aioredis.TimeoutError, asyncio.TimeoutError) as e:
                delay = backoff.get_delay(retry)
                if retry == self._max_connection_retries - 1:
                    REDIS_HEALTH.set(0)
                    raise
                await asyncio.sleep(delay)

    async def execute_cached(self, key: str, *args: Any, **kwargs: Any) -> Any:
        if result := await self._command_cache.get(key):
            return result

        result = await self.execute(*args, **kwargs)
        await self._command_cache.set(key, result)
        return result

    async def execute_batch(self, operations: List[Tuple[str, List[Any]]], transaction: bool = True) -> List[Any]:
        async with self.connection() as conn:
            if transaction:
                async with conn.pipeline(transaction=True) as pipe:
                    for op_name, args in operations:
                        getattr(pipe, op_name)(*args)
                    return await pipe.execute()
            else:
                return await asyncio.gather(*[
                    getattr(conn, op_name)(*args)
                    for op_name, args in operations
                ])

    async def execute_pipeline(self, commands: List[Tuple[str, List[Any]]]) -> List[Any]:
        async with self._get_connection() as conn:
            tr = conn.pipeline(transaction=True)
            for cmd, args in commands:
                getattr(tr, cmd)(*args)
            return await tr.execute()

    async def _setup_connection(self, conn: aioredis.Redis) -> None:
        await conn.client_setname(f"bot_{id(self)}_{time.time()}")
        await conn.config_set('client-output-buffer-limit', 'normal 0 0 0')

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