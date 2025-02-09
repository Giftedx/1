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
    def __init__(self, bot: MediaStreamingBot):
        self.bot = bot
        self._active_streams: Dict[str, AsyncExitStack] = {}

    @commands.command(name='play')
    @measure_latency("play_command")
    async def play(self, ctx: commands.Context, *, media_query: str):
        """Play media based on user query."""
        DISCORD_COMMANDS.inc()
        try:
            # Sanitize user input
            if not SecurityValidator.validate_media_path(media_query):
                raise InvalidCommandError("Invalid media query format.")

            # Search for the media
            media_path = await self.bot.plex_manager.search_media(media_query)
            if not media_path:
                raise MediaNotFoundError(f"Media not found: {media_query}")

            # Add the media request to the queue
            await self.bot.queue_manager.add_item(media_path)
            await ctx.send(f"Added '{media_query}' to the queue.")

        except MediaNotFoundError as e:
            await ctx.send(f"Media not found: {media_query}. Details: {e}")
        except QueueFullError as e:
            await ctx.send(f"The queue is currently full. Details: {e}")
        except RateLimitExceededError as e:
            await ctx.send(f"You are being rate limited. Please try again later. Details: {e}")
        except InvalidCommandError as e:
            await ctx.send(f"Invalid command format. Details: {e}")
        except StreamingError as e:
            await ctx.send(f"Streaming error: {e}")
        except aiohttp.ClientError as e:
            logger.exception(f"Network error in play command: {e}")
            await ctx.send(f"A network error occurred: {e}")
        except Exception as e:
            logger.exception(f"Error in play command: {e}")
            await ctx.send(f"An unexpected error occurred: {e}")

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