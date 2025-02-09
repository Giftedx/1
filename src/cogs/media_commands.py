import asyncio
import json
import logging
import os
import discord
from discord.ext import commands
from pydantic import BaseModel, validator
from src.core.exceptions import QueueFullError, RateLimitExceededError, MediaNotFoundError
from src.security.input_validation import SecurityValidator
from src.utils.performance import measure_latency
from functools import partial
from typing import Optional, Dict
from contextlib import AsyncExitStack
from src.bot.main import MediaStreamingBot  # Import the class

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
            media_query = SecurityValidator.sanitize_html(media_query)

            # Basic validation to prevent empty queries
            if not media_query:
                await ctx.send("Please provide a media title to play.")
                return

            # Search for the media
            media_info = await self.bot.plex_manager.search_media(media_query)
            if not media_info:
                await ctx.send(f"Media '{media_query}' not found.")
                return

            # Get the stream URL
            stream_url = await self.bot.plex_manager.get_stream_url(media_info[0])
            if not stream_url:
                await ctx.send(f"Could not retrieve stream URL for '{media_query}'.")
                return

            # Connect to voice channel and play media
            voice_channel = ctx.author.voice.channel
            if not voice_channel:
                await ctx.send("You must be in a voice channel to use this command.")
                return

            await self.bot.media_player.play(stream_url, voice_channel)
            await ctx.send(f"Now playing '{media_info[0].title}'.")

        except MediaNotFoundError:
            await ctx.send(f"Media '{media_query}' not found.")
        except StreamingError as e:
            await ctx.send(f"Streaming error: {e}")
        except Exception as e:
            logger.exception(f"Error in play command: {e}")
            await ctx.send(f"An error occurred: {e}")

    @commands.command(name='queue')
    @measure_latency("queue_command")
    async def queue(self, ctx: commands.Context):
        """
        Display the current media queue.
        """
        try:
            queue_items = await self.bot.redis_manager.execute('LRANGE', 'media_queue', 0, -1)
            if queue_items:
                queue_list = "\n".join([item.decode('utf-8') for item in queue_items])
                await ctx.send(f"Current Queue:\n{queue_list}")
            else:
                await ctx.send("The queue is currently empty.")

        except Exception as e:
            logger.exception(f"Error retrieving queue: {e}")
            await ctx.send("Could not retrieve the queue. Check the logs for details.")