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
from typing import Optional
from contextlib import AsyncExitStack

logger = logging.getLogger(__name__)

class MediaRequest(BaseModel):
    title: str
    path: str
    requester: str
    quality: str = "medium"

    @validator('path')
    def validate_path(cls, v):
        if not os.path.exists(v):
            raise ValueError("Media file does not exist")
        return v

class MediaCommands(commands.Cog):
    """
    Cog containing media‑related commands.
    """
    def __init__(self, bot: "MediaStreamingBot"):
        self.bot = bot
        self._active_streams: Dict[str, AsyncExitStack] = {}

    @commands.command(name='play')
    @measure_latency("play_command")
    async def play(self, ctx: commands.Context, *, media_query: str):
        async with AsyncExitStack() as stack:
            try:
                # Validate input first
                if not media_query or not SecurityValidator.validate_media_path(media_query):
                    await ctx.send("❌ Invalid media query")
                    return

                # Check rate limit
                if await self.bot.rate_limiter.is_rate_limited(str(ctx.author.id)):
                    raise RateLimitExceededError("Rate limit exceeded")

                # Search media
                items = await self.bot.plex_server.search_media(media_query)
                if not items:
                    await ctx.send("❌ No media found.")
                    return

                # Set up streaming
                item = items[0]
                media_req = MediaRequest(
                    title=item.title,
                    path=item.media[0].parts[0].file,
                    requester=str(ctx.author.id),
                    quality=self.bot.config.DEFAULT_QUALITY.value
                )

                # Add to queue and start streaming
                await self.bot.queue_manager.add(media_req.dict())
                stream_ctx = self.bot.ffmpeg_manager.stream_session(
                    media_req.path, media_req.quality)
                await stack.enter_async_context(stream_ctx)
                
                # Store the stack for cleanup
                self._active_streams[media_req.path] = stack.pop_all()
                
                await ctx.send(f"✅ Added {media_req.title} to the queue.")
                
            except Exception as e:
                logger.error(f"Error in play command: {e}", exc_info=True)
                await ctx.send(f"❌ {str(e)}")

    @commands.command(name='queue')
    @measure_latency("queue_command")
    async def queue(self, ctx: commands.Context):
        """
        Display the current media queue.
        """
        try:
            queue_items = await self.bot.redis_manager.execute('LRANGE', 'media_queue', 0, -1)
            if not queue_items:
                await ctx.send("The queue is empty.")
                return

            embed = discord.Embed(title="Media Queue", colour=discord.Colour.blue())
            for idx, item in enumerate(queue_items, start=1):
                media = json.loads(item)
                embed.add_field(
                    name=f"{idx}. {media['title']}",
                    value=f"Requested by <@{media.get('requester', 'unknown')}>",
                    inline=False
                )
            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in 'queue' command: {e}")
            await ctx.send("❌ An error occurred while retrieving the queue.")