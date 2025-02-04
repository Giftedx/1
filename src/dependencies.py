import asyncio
from typing import AsyncGenerator, TypeVar, Generic, Dict, Callable, Awaitable, AsyncContextManager
from contextlib import asynccontextmanager
from dataclasses import dataclass
from src.utils.config import Config
from src.core.redis_manager import RedisManager
from src.plex_server import PlexServer
from src.metrics import ACTIVE_STREAMS, ActiveStreams
from src.core.backpressure import Backpressure
from src.core.circuit_breaker import CircuitBreaker

T = TypeVar('T')

@dataclass
class ResourceConfig:
    max_retries: int = 3
    retry_delay: float = 1.0
    timeout: float = 30.0

class ResourceManager(Generic[T]):
    def __init__(self, config: ResourceConfig):
        self.config = config
        self._resources: Dict[str, T] = {}
        self._metrics = METRICS
        self._resource_stats: Dict[str, Dict[str, float]] = {}
        self._cleanup_hooks: Dict[str, Callable] = {}

    async def get_or_create(self, key: str, factory: Callable[[], Awaitable[T]]) -> T:
        if key not in self._resources:
            for attempt in range(self.config.max_retries):
                try:
                    resource = await asyncio.wait_for(factory(), self.config.timeout)
                    self._resources[key] = resource
                    self._metrics.increment('resource_creation_success', labels={'type': key})
                    return resource
                except Exception as e:
                    self._metrics.increment('resource_creation_error', 
                                          labels={'type': key, 'error': type(e).__name__})
                    if attempt == self.config.max_retries - 1:
                        raise
                    await asyncio.sleep(self.config.retry_delay * (attempt + 1))
        return self._resources[key]

    @asynccontextmanager
    async def resource_context(self, key: str) -> AsyncContextManager[T]:
        """Manage resource lifecycle with metrics."""
        start_time = time.monotonic()
        try:
            resource = await self.get_or_create(key)
            yield resource
        finally:
            duration = time.monotonic() - start_time
            self._resource_stats[key] = {
                'last_access': time.monotonic(),
                'usage_duration': duration
            }

async def provide_redis_manager(config: Config) -> RedisManager:
    return await RedisManager.create(str(config.REDIS_URL), config.REDIS_POOL_SIZE)

@asynccontextmanager
async def get_redis_manager(config: Config) -> AsyncGenerator[RedisManager, None]:
    manager = await RedisManager.create(
        redis_url=str(config.REDIS_URL),
        pool_size=config.REDIS_POOL_SIZE,
        max_retries=3
    )
    try:
        yield manager
    finally:
        await manager.close()

async def provide_plex_server(config: Config) -> PlexServer:
    return PlexServer(str(config.PLEX_URL), config.PLEX_TOKEN)

def provide_active_streams() -> ActiveStreams:
    return ACTIVE_STREAMS

def provide_backpressure() -> Backpressure:
    return Backpressure(max_concurrent=100, max_queue_size=1000)

def provide_circuit_breaker() -> CircuitBreaker:
    return CircuitBreaker(failure_threshold=5, reset_timeout=30)