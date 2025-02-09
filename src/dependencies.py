import asyncio
from typing import AsyncGenerator, TypeVar, Generic, Dict, Callable, Awaitable, AsyncContextManager, Optional
from contextlib import asynccontextmanager
from dataclasses import dataclass
from src.utils.config import Config
from src.core.redis_manager import RedisManager
from src.plex_server import PlexServer
from src.metrics import ACTIVE_STREAMS, ActiveStreams
from src.core.backpressure import Backpressure
from src.core.circuit_breaker import CircuitBreaker
from cachetools import TTLCache
from src.utils.retry import ExponentialBackoff
from dependency_injector import containers, providers
from src.services.queue_manager import QueueManager

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
        self._retry_backoff = ExponentialBackoff(min_delay=1.0, max_delay=30.0)
        self._resource_cache = TTLCache(maxsize=100, ttl=3600)
        self._resource_monitor = ResourceMonitor()
        self._cleanup_scheduler = CleanupScheduler()
        self._resource_lifecycle = ResourceLifecycleManager(
            max_idle_time=300,
            cleanup_interval=60
        )
        self._health_monitor = HealthMonitor(
            check_interval=30,
            failure_threshold=3
        )

    async def get_or_create(self, key: str, factory: Callable[[], Awaitable[T]]) -> T:
        if resource := await self._get_cached_resource(key):
            return resource

        async with self._resource_lock(key):
            return await self._create_and_cache_resource(key, factory)

    async def _get_cached_resource(self, key: str) -> Optional[T]:
        if resource := self._resource_cache.get(key):
            if await self._health_monitor.is_healthy(resource):
                return resource
            await self._cleanup_resource(key, resource)
        return None

    async def cleanup_resources(self) -> None:
        stale_resources = await self._resource_monitor.get_stale_resources()
        for resource in stale_resources:
            await self._cleanup_resource(resource)
            
    async def _cleanup_resource(self, resource: T) -> None:
        if hasattr(resource, 'close'):
            await resource.close()
        elif hasattr(resource, 'cleanup'):
            await resource.cleanup()

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

class Container(containers.DeclarativeContainer):
    config = providers.Singleton(Config)
    
    redis_manager = providers.Singleton(
        RedisManager.create,
        redis_url=config.provided.REDIS_URL,
        pool_size=config.provided.REDIS_POOL_SIZE
    )
    
    plex_server = providers.Singleton(
        PlexServer,
        base_url=config.provided.PLEX_URL,
        token=config.provided.PLEX_TOKEN
    )
    
    queue_manager = providers.Singleton(
        QueueManager,
        redis_manager=redis_manager
    )