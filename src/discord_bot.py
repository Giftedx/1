import os
import logging
import asyncio
import discord
from discord.ext import commands
from src.plex_server import PlexServer  # robust Plex integration
from dependency_injector.wiring import inject, Provide
from src.core.di_container import Container
from src.core.plex_manager import PlexManager

logger = logging.getLogger(__name__)

class MediaBot(commands.Bot):
    @inject
    def __init__(
        self,
        plex_manager: PlexManager = Provide[Container.plex_manager],
        *args,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.plex_manager = plex_manager

    async def on_ready(self):
        logger.info(f"Discord Bot logged in as {self.user}")

    async def handle_command_error(self, ctx: commands.Context, error: Exception):
        """Centralized error handler for command errors."""
        logger.error(f"Error in command {ctx.command}: {error}", exc_info=True)
        
        # Enhanced error message for different error types
        if isinstance(error, commands.CommandNotFound):
            await ctx.send("❌ Command not found.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Missing required argument: {error.param.name}")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("❌ Invalid argument provided.")
        else:
            await ctx.send(f"❌ An unexpected error occurred: {error}")

    @commands.command(name="play")
    async def play_media(self, ctx, *, media: str):
        try:
            media_info = await self.plex_manager.search_media(media)
            if not media_info:
                await ctx.send("Media not found.")
                return
            await ctx.send(f"Playing {media_info[0].title}...")
        except Exception as e:
            logger.error(f"Error in play command: {e}", exc_info=True)
            await ctx.send("An error occurred.")

# Initialize logging, add production logging level setup here
logging.basicConfig(level=logging.INFO)

# Instantiate bot with command prefix and intents
intents = discord.Intents.default()
intents.message_content = True
bot = MediaBot(command_prefix="!", intents=intents)

@bot.event
async def on_command_error(ctx, error):
    await bot.handle_command_error(ctx, error)

if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        logging.error("DISCORD_BOT_TOKEN not set")
        exit(1)
    bot.run(token)
