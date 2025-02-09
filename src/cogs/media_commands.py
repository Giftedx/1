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
        async with ctx.typing():
            try:
                if not media_query or not SecurityValidator.validate_media_path(media_query):
                    await ctx.send("❌ Invalid media query.")
                    return

                if await self.bot.rate_limiter.is_rate_limited(str(ctx.author.id)):
                    await ctx.send("❌ Rate limit exceeded. Please try again later.")
                    return

                items = await self.bot.plex_server.search_media(media_query)
                if not items:
                    await ctx.send("❌ No media found.")
                    return

                item = items[0]
                media_req = MediaRequest(
                    title=item.title,
                    path=item.media[0].parts[0].file,
                    requester=str(ctx.author.id),
                    quality=self.bot.config.DEFAULT_QUALITY.value
                )

                await self.bot.queue_manager.add(media_req.dict())
                async with self.bot.ffmpeg_manager.stream_session(media_req.path, media_req.quality):
                    # Replace with an actual streaming routine instead of sleep.
                    await asyncio.sleep(1)
                await ctx.send(f"✅ Added {media_req.title} to the queue.")
            except (QueueFullError, RateLimitExceededError, MediaNotFoundError) as specific_err:
                logger.error(f"Media play error: {specific_err}")
                await ctx.send(f"❌ Error: {specific_err}")
            except Exception as e:
                logger.error(f"Unhandled error in play command: {e}", exc_info=True)
                await ctx.send("❌ An unexpected error occurred.")
                
    @commands.command(name='queue')
    @measure_latency("queue_command")
    async def queue(self, ctx: commands.Context):
        """
        Display the current media queue.
        """
        try:
            queue_items = await self.bot.redis_manager.execute('LRANGE', 'media_queue', 0, -1)
            if not queue_items:
                await ctx.send("ℹ️ The media queue is empty.")
                return

            embed = discord.Embed(title="Media Queue", colour=discord.Colour.blue())
            for idx, item in enumerate(queue_items, start=1):
                embed.add_field(name=f"Item {idx}", value=item, inline=False)
            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in 'queue' command: {e}", exc_info=True)
            await ctx.send("❌ An error occurred while retrieving the queue.")