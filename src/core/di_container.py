from dependency_injector import containers, providers
from src.core.redis_manager import RedisManager
from src.core.ffmpeg_manager import FFmpegManager, ResourceLimits
from src.core.queue_manager import QueueManager
from src.plex_server import PlexServer
from src.utils.config import Config
from src.core.health_check import HealthCheck
from src.utils.rate_limiter import RateLimiter

class Container(containers.DeclarativeContainer):
    config = providers.Singleton(Config)
    
    redis_manager = providers.Singleton(
        RedisManager,
        redis_url=config.provided.REDIS_URL,
        pool_size=config.provided.REDIS_POOL_SIZE
    )
    
    resource_limits = providers.Singleton(
        ResourceLimits,
        max_cpu_percent=80.0,
        max_memory_mb=1024,
        max_processes=config.provided.MAX_CONCURRENT_STREAMS
    )
    
    ffmpeg_manager = providers.Singleton(
        FFmpegManager,
        virtual_cam=config.provided.VIRTUAL_CAM_DEVICE,
        video_width=config.provided.VIDEO_WIDTH,
        video_height=config.provided.VIDEO_HEIGHT,
        loglevel=config.provided.FFMPEG_LOGLEVEL,
        resource_limits=providers.Singleton(ResourceLimits,
                                            max_cpu_percent=80.0,
                                            max_memory_mb=1024,
                                            max_processes=config.provided.MAX_CONCURRENT_STREAMS)
    )
    
    queue_manager = providers.Singleton(
        QueueManager,
        max_length=config.provided.MAX_QUEUE_LENGTH,
        redis_manager=redis_manager
    )
    
    health_check = providers.Singleton(HealthCheck)
    
    rate_limiter = providers.Singleton(
        RateLimiter,
        max_requests=config.provided.RATE_LIMIT_REQUESTS,
        window_seconds=config.provided.RATE_LIMIT_PERIOD
    )

class DIContainer:
    _services = {}

    @classmethod
    def register(cls, key: str, service) -> None:
        cls._services[key] = service

    @classmethod
    def resolve(cls, key: str):
        return cls._services.get(key)
