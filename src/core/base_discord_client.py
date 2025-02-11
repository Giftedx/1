from typing import Optional
import logging
import discord
from discord.ext import commands
from dependency_injector.wiring import inject, provide

from src.config import Config
from src.services.plex_server import PlexServer

from src.utils.redis_manager import RedisManager

logger = logging.getLogger(__name__)

class BaseDiscordClient(commands.Bot):
    @inject
    def __init__(self, config: Config):
        super().__init__(
            command_prefix=config.COMMAND_PREFIX,
            intents=discord.Intents.all()
        )
        self.config = config
        self._setup_error_handlers()

    async def setup_hook(self) -> None:
        await self._initialize_services()

    @inject
    async def _initialize_services(self, 
        redis_manager: RedisManager = provide("redis_manager"),
        plex_server: PlexServer = provide("plex_server"),
        
    ) -> None:
        self.redis_manager = redis_manager
        self.plex_server = plex_server
        
        
    def _setup_error_handlers(self) -> None:
        @self.event
        async def on_error(event: str, *args, **kwargs) -> None:
            logger.exception(f"Error in {event}")

        @self.event
        async def on_command_error(ctx: commands.Context, error: Exception) -> None:
            if isinstance(error, commands.CommandNotFound):
                return
            logger.exception(f"Command error: {error}")
