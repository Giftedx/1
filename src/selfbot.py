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
import os

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

class StreamingSelfBot(commands.Bot):
    """
    Self‑bot account for streaming via Plex. Uses a separate token.
    """
    def __init__(self, config: Config):
        intents = discord.Intents.default()  # Minimal intents for self‑bot functionality.
        super().__init__(command_prefix="!", self_bot=True, intents=intents)
        self.config = config
        self.redis_manager: Optional[RedisManager] = None
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
            await self._cleanup()
            self._shutdown_event.set()
        await super().close()
        logger.info("Self‑bot shutdown complete.")

    async def _cleanup(self):
        tasks = [t for t in self._cleanup_tasks if not t.done()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self.redis_manager:
            await self.redis_manager.close()
        ACTIVE_STREAMS.decrement()

    async def on_ready(self):
        logger.info(f"Self‑bot logged in as {self.user}")

    async def on_message(self, message):
        # Only respond to DM commands to ensure selfbot safety
        if message.guild is not None: 
            return

        if message.content.startswith("!play"):
            parts = message.content.split(maxsplit=1)
            if len(parts) != 2:
                await message.channel.send("Usage: !play <media_url_or_path>")
                return
            media = parts[1]
            # Use the VOICE_CHANNEL_ID from env
            if VOICE_CHANNEL_ID is None:
                await message.channel.send("VOICE_CHANNEL_ID is not configured correctly.")
                return
            channel = self.get_channel(VOICE_CHANNEL_ID)
            if not channel or not isinstance(channel, discord.VoiceChannel):
                await message.channel.send("Invalid or misconfigured voice channel.")
                return
            await initiate_voice_playback(channel, media)

# Read the voice channel ID from env (ensure this variable is set in .env)
VOICE_CHANNEL_ID = os.getenv("VOICE_CHANNEL_ID")
if VOICE_CHANNEL_ID:
    try:
        VOICE_CHANNEL_ID = int(VOICE_CHANNEL_ID)
    except ValueError:
        logging.error("Invalid VOICE_CHANNEL_ID. Must be an integer.")
        VOICE_CHANNEL_ID = None  # Set to None if invalid
else:
    VOICE_CHANNEL_ID = None

# Enhanced voice playback using robust session management and error handling.
async def initiate_voice_playback(channel, media: str):
    vc = None
    try:
        vc = await channel.connect()
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-i", media, "-f", "s16le", "-ar", "48000", "-ac", "2", "pipe:1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        while True:
            data = await process.stdout.read(4096)
            if not data:
                break  # no more data, exit loop
            await vc.send_audio_packet(data)
        await process.wait()
        logging.info("Playback finished.")
    except Exception as e:
        logging.exception("Voice playback error")
    finally:
        if vc:
            await vc.disconnect()

if __name__ == "__main__":
    from src.utils.config import Config
    config = Config()
    bot = StreamingSelfBot(config)
    asyncio.run(bot.start(os.getenv("DISCORD_SELFBOT_TOKEN")))