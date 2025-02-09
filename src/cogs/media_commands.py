import os
import logging
import aiohttp
from discord.ext import commands
from pydantic import BaseModel, validator
from src.core.exceptions import QueueFullError, RateLimitExceededError, MediaNotFoundError, InvalidCommandError, StreamingError
from src.security.input_validation import SecurityValidator
from src.utils.performance import measure_latency
from functools import partial
from typing import Optional, Dict
from contextlib import AsyncExitStack
from src.bot.main import MediaStreamingBot  # Import the class
from src.metrics import DISCORD_COMMANDS  # Import DISCORD_COMMANDS
from dependency_injector.wiring import inject, Provide
from src.core.di_container import Container
from src.core.plex_manager import PlexManager
from src.core.media_player import MediaPlayer
from src.core.queue_manager import QueueManager
from src.core.rate_limiter import RateLimiter
from src.core.config import Settings

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
    async def play(self, ctx: commands.Context, media_title: str):
        """Plays media in a voice channel."""
        try:
            # Get the voice channel the user is in
            voice_channel = ctx.author.voice.channel
            if not voice_channel:
                await ctx.send("You must be in a voice channel to use this command.")
                return

            # Ensure the bot is connected to the voice channel
            bot = ctx.bot  # Get the bot instance from the context
            if bot.voice_client is None or not bot.voice_client.is_connected():
                try:
                    bot.voice_client = await voice_channel.connect()
                    VOICE_CONNECTIONS.inc()
                    logger.info(f"Connected to voice channel: {voice_channel.name}")
                except Exception as e:
                    logger.error(f"Failed to connect to voice channel: {e}", exc_info=True)
                    await ctx.send(f"Failed to connect to voice channel: {e}")
                    return

            # Search for the media using PlexManager
            try:
                media_items = await self.plex_manager.search_media(media_title)
                if not media_items:
                    await ctx.send(f"Media '{media_title}' not found.")
                    return
                
                # If multiple items are found, let the user choose
                if len(media_items) > 1:
                    # Create an embed to list the media items
                    embed = discord.Embed(title="Multiple Media Found", description="Please select the media you want to play:")
                    for i, item in enumerate(media_items):
                        embed.add_field(name=f"{i+1}", value=item.title, inline=False)
                    
                    message = await ctx.send(embed=embed)
                    
                    # Add reactions for the user to select the media
                    for i in range(1, len(media_items) + 1):
                        await message.add_reaction(f"{i}\N{COMBINING ENCLOSING KEYCAP}")
                    
                    def check(reaction, user):
                        return user == ctx.author and str(reaction.emoji) in [f"{i}\N{COMBINING ENCLOSING KEYCAP}" for i in range(1, len(media_items) + 1)]
                    
                    try:
                        reaction, user = await bot.wait_for('reaction_add', timeout=60.0, check=check)
                    except asyncio.TimeoutError:
                        await ctx.send("You took too long to respond.")
                        return
                    else:
                        selected_index = int(str(reaction.emoji)[0]) - 1
                        media_item = media_items[selected_index]
                        await ctx.send(f"You selected: {media_item.title}")
                else:
                    media_item = media_items[0]

            except MediaNotFoundError:
                await ctx.send(f"Media '{media_title}' not found in Plex.")
                return
            except Exception as e:
                logger.error(f"Plex search failed: {e}", exc_info=True)
                await ctx.send(f"Plex search failed: {e}")
                return

            # Get the stream URL
            try:
                stream_url = await self.plex_manager.get_stream_url(media_item)
            except StreamingError as e:
                logger.error(f"Could not get stream URL: {e}", exc_info=True)
                await ctx.send(f"Could not get stream URL: {e}")
                return
            except Exception as e:
                logger.error(f"Unexpected error getting stream URL: {e}", exc_info=True)
                await ctx.send(f"Unexpected error getting stream URL: {e}")
                return

            # Play the media using MediaPlayer
            try:
                await self.media_player.play(stream_url, bot.voice_client)
                await ctx.send(f"Now playing: {media_item.title}")
            except StreamingError as e:
                logger.error(f"Streaming failed: {e}", exc_info=True)
                await ctx.send(f"Streaming failed: {e}")
            except Exception as e:
                logger.error(f"Unexpected streaming error: {e}", exc_info=True)
                await ctx.send(f"Unexpected streaming error: {e}")

        except Exception as e:
            logger.error(f"Error in play_media function: {e}", exc_info=True)
            await ctx.send(f"An error occurred: {e}")

    @commands.command(name='queue')
    @measure_latency("queue_command")
    async def queue(self, ctx: commands.Context):
        """
        Display the current media queue.
        """
        try:
            queue_length = await self.bot.queue_manager.redis.llen(self.bot.queue_manager.queue_key)
            await ctx.send(f"Items in queue: {queue_length}")

        except Exception as e:
            logger.exception(f"Error in queue command: {e}")
            await ctx.send(f"An unexpected error occurred: {e}")