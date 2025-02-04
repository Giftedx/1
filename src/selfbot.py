import asyncio
import logging
from typing import Optional, Set
import discord
from discord.ext import commands
from src.utils.config import Config
from src.core.redis_manager import RedisManager
from src.core.circuit_breaker import CircuitBreaker
from src.core.queue_manager import QueueManager
from src.core.ffmpeg_manager import FFmpegManager
from src.plex_server import PlexServer
from src.utils.rate_limiter import RateLimiter
from src.core.exceptions import MediaNotFoundError
from src.metrics import ACTIVE_STREAMS, METRICS

logger = logging.getLogger(__name__)

class StreamingSelfBot(commands.Bot):
    """
    Self‑bot account for streaming via Plex. Uses a separate token.
    """
    def __init__(self, config: Config):
        intents = discord.Intents.default()  # Minimal intents for self‑bot functionality.
        super().__init__(command_prefix="!", self_bot=True, intents=intents)
        self.config = config
        self.redis_manager = None
        self.circuit_breaker = CircuitBreaker(
            config.CIRCUIT_BREAKER_THRESHOLD,
            config.CIRCUIT_BREAKER_TIMEOUT
        )
        self.queue_manager = None
        self.ffmpeg_manager = None
        self.plex_server = None
        self.rate_limiter = RateLimiter(
            config.RATE_LIMIT_REQUESTS,
            config.RATE_LIMIT_PERIOD
        )
        self._cleanup_tasks: Set[asyncio.Task] = set()
        self._shutdown_event = asyncio.Event()
        self._startup_complete = asyncio.Event()

    async def setup_hook(self):
        try:
            self.redis_manager = await RedisManager.create(
                str(self.config.REDIS_URL),
                self.config.REDIS_POOL_SIZE
            )
            self.rate_limiter.set_redis_manager(self.redis_manager)
            self.queue_manager = QueueManager(self.config.MAX_QUEUE_LENGTH, self.redis_manager)
            self.ffmpeg_manager = FFmpegManager(
                self.config.VIRTUAL_CAM_DEVICE,
                self.config.VIDEO_WIDTH,
                self.config.VIDEO_HEIGHT,
                self.config.FFMPEG_LOGLEVEL
            )
            self.plex_server = PlexServer(str(self.config.PLEX_URL), self.config.PLEX_TOKEN)
            ACTIVE_STREAMS.increment()
            METRICS.increment('bot_startups')
            self._startup_complete.set()
            logger.info("Self‑bot setup complete.")
        except Exception as e:
            METRICS.increment('bot_startup_failures')
            logger.error(f"Setup failed: {e}", exc_info=True)
            raise

    async def close(self):
        if not self._shutdown_event.is_set():
            self._shutdown_event.set()
            METRICS.increment('bot_shutdowns')
            await self._cleanup()
        await super().close()
        logger.info("Self‑bot shutdown complete.")

    async def _cleanup(self):
        tasks = [t for t in self._cleanup_tasks if not t.done()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.redis_manager.close()
        ACTIVE_STREAMS.decrement()

    async def on_ready(self):
        logger.info(f"Self‑bot logged in as {self.user}")

if __name__ == "__main__":
    import os
    from src.utils.config import Config
    config = Config()
    bot = StreamingSelfBot(config)
    bot.run(os.environ.get("STREAMING_BOT_TOKEN"))