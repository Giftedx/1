import logging
import asyncio
from typing import Optional
import discord
from discord.ext import commands
from src.core.plex_manager import PlexManager
from src.core.media_player import MediaPlayer
from src.core.queue_manager import QueueManager
from src.metrics import DISCORD_COMMANDS, VOICE_CONNECTIONS
from src.core.rate_limiter import RateLimiter
from src.core.exceptions import MediaNotFoundError, StreamingError

logger = logging.getLogger(__name__)

class MediaBot(commands.Bot):
    def __init__(self, config, plex_manager: PlexManager, media_player: MediaPlayer):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=config.COMMAND_PREFIX, intents=intents)
        self.config = config
        self.plex = plex_manager
        self.media_player = media_player
        self.queue = QueueManager()
        self.rate_limiter = RateLimiter()
        self._error_count = 0
        self._last_error = None
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5
        self._reconnect_delay = 5

    async def setup_hook(self):
        await self.load_extension("src.bot.commands")
        await self.load_extension("src.bot.events")

    async def on_ready(self):
        logger.info(f"Bot ready: {self.user}")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{self.command_prefix}help"
            )
        )

    async def on_command_error(self, ctx, error):
        self._error_count += 1
        self._last_error = error
        DISCORD_COMMANDS.labels(status='error').inc()
        
        if isinstance(error, MediaNotFoundError):
            await ctx.send("❌ Could not find the requested media. Please check your search terms.")
            return
            
        if isinstance(error, StreamingError):
            await ctx.send("❌ Failed to start media playback. Please try again later.")
            return

        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"Please wait {error.retry_after:.1f}s before using this command again.")
            return

        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You don't have permission to use this command.")
            return

        logger.error(f"Command error: {error}", exc_info=error)
        await ctx.send("An error occurred. Please try again later.")

    async def handle_voice_state_update(self, member, before, after):
        if member == self.user:
            if before.channel and not after.channel:
                VOICE_CONNECTIONS.dec()
            elif after.channel and not before.channel:
                VOICE_CONNECTIONS.inc()

    async def ensure_voice_client(self, channel):
        for attempt in range(self._max_reconnect_attempts):
            try:
                return await super().ensure_voice_client(channel)
            except Exception as e:
                self._reconnect_attempts += 1
                if attempt == self._max_reconnect_attempts - 1:
                    raise
                await asyncio.sleep(self._reconnect_delay * (attempt + 1))

    def run(self, token: str):
        async def runner():
            try:
                await self.start(token)
            finally:
                await self.close()

        asyncio.run(runner())

@bot.command(name="play")
async def play_media(ctx, *, media: str):
    # Example usage of Plex:
    plex_url = os.getenv("PLEX_URL")
    plex_token = os.getenv("PLEX_TOKEN")
    if not plex_url or not plex_token:
        await ctx.send("Plex server not configured.")
        return

    plex_client = PlexServer(plex_url, plex_token)
    # Retrieve the media file/URL...
    try:
        # ...
        await ctx.send(f"Playing {media} now...")
        # Connect to voice / stream via FFmpeg or hand off to another system
    except MediaNotFoundError:
        raise
    except Exception as e:
        logger.error(f"Playback error: {e}", exc_info=True)
        raise StreamingError(str(e))
