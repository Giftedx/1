import discord
import logging
from src.core.config import Settings
from src.bot.discord_bot import MediaBot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True
settings = Settings()
bot = MediaBot(settings=settings, command_prefix=settings.COMMAND_PREFIX, intents=intents)


@bot.event
async def on_ready() -> None:
    logger.info(f"Logged in as {bot.user}")


if __name__ == "__main__":
    bot.run(settings.DISCORD_BOT_TOKEN)
