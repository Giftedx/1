from dependency_injector import containers, providers
from src.utils.config import Settings
from src.core.redis_manager import RedisManager
from src.utils.rate_limiter import RateLimiter
from src.core.plex_manager import PlexManager
from src.core.ffmpeg_manager import FFmpegManager
from src.core.queue_manager import QueueManager
from src.monitoring.alerts import PrometheusAlerts


class Container(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration(modules=[
        "src.bot.discord_bot",  # Example: Wire the Discord bot module
        "src.cogs.media_commands",  # Example: Wire the Media Commands cog
        "src.selfbot.selfbot"  # Example: Wire the Selfbot
    ])

    config = providers.Configuration()
    settings = providers.Singleton(Settings)

    redis_manager = providers.Singleton(
        RedisManager,
        url=settings.provided.REDIS_URL,
        pool_size=settings.provided.REDIS_POOL_SIZE
    )

    rate_limiter = providers.Singleton(
        RateLimiter,
        max_requests=settings.provided.RATE_LIMIT_REQUESTS,
        window_seconds=settings.provided.RATE_LIMIT_PERIOD,
        redis_manager=redis_manager
    )

    plex_manager = providers.Singleton(
        PlexManager,
        url=settings.provided.PLEX_URL,
        token=settings.provided.PLEX_TOKEN
    )

    ffmpeg_manager = providers.Singleton(FFmpegManager)

    queue_manager = providers.Singleton(
        QueueManager,
        max_length=settings.provided.MAX_QUEUE_LENGTH,
        redis_manager=redis_manager
    )

    prometheus_alerts = providers.Singleton(
        PrometheusAlerts,
        alert_config=settings.provided.ALERT_CONFIG
    )
