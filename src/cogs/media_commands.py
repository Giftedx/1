import os
import logging
from discord.ext import commands
from pydantic import BaseModel, validator
from src.security.input_validation import SecurityValidator
from src.utils.performance import measure_latency
from dependency_injector.wiring import inject, Provide

from src.core.di_container import Container
from src.core.plex_manager import PlexManager
from src.core.media_player import MediaPlayer
from src.core.queue_manager import QueueManager
from src.core.rate_limiter import RateLimiter
from src.core.config import Settings

from src.bot.discord_bot import play_media


logger = logging.getLogger(__name__)


class MediaRequest(BaseModel):

    title: str
    path: str
    requester: str
    quality: str = "medium"

    @validator('path')
    def validate_path(cls, v):
        # A more robust check
        if not os.path.exists(v):
            raise ValueError("Media file does not exist at the specified path.")
        if not SecurityValidator.validate_media_path(v):
            raise ValueError("Invalid media path format.")
        return v


class MediaCommands(commands.Cog):
    """
    Cog containing media‑related commands.
    """
    @inject
    def __init__(
        self,
        bot: commands.Bot,
        settings: Settings = Provide[Container.settings],
        plex_manager: PlexManager = Provide[Container.plex_manager],
        media_player: MediaPlayer = Provide[Container.media_player],
        queue_manager: QueueManager = Provide[Container.queue_manager],
        rate_limiter: RateLimiter = Provide[Container.rate_limiter],
    ):
        self.bot = bot
        self.validator = SecurityValidator()
        self.settings = settings
        self.plex_manager = plex_manager
        self.media_player = media_player
        self.queue_manager = queue_manager
        self.rate_limiter = rate_limiter

    @commands.command(name='play')
    @measure_latency("play_command")
    async def play(self, ctx: commands.Context, *, media_title: str):
        """Plays media in a voice channel."""
        await play_media(ctx, media_title, self.plex_manager, self.media_player)

    @commands.command(name='stop')
    @measure_latency("stop_command")
    async def stop(self, ctx: commands.Context) -> None:
        """Stops the currently playing media."""
        try:
            if ctx.voice_client:
                await ctx.voice_client.disconnect()
                await ctx.send("Stopped playing.")
            else:
                await ctx.send("Not connected to a voice channel.")
        except Exception as e:
            logger.error(f"Error in stop command: {str(e)}", exc_info=True)
            await ctx.send(f"An error occurred: {str(e)}")

    @commands.command(name='queue')
    @measure_latency("queue_command")
    async def queue(self, ctx: commands.Context) -> None:
        """
        Display the current media queue.
        """
        try:
            queue_length = await self.bot.queue_manager.redis.llen(self.bot.queue_manager.queue_key)
            await ctx.send(f"Items in queue: {queue_length}")

        except Exception as e:
            logger.exception(f"Error in queue command: {e}")
            await ctx.send(f"An unexpected error occurred: {e}")