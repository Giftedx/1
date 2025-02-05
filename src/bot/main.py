import discord
from discord.ext import commands
import logging
from src.utils.config import settings
from src.media.processor import MediaProcessor
from src.utils.plex import PlexClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=settings.COMMAND_PREFIX, intents=intents)
media_processor = MediaProcessor()
plex_client = PlexClient(settings.PLEX_URL, settings.PLEX_TOKEN)

@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user}')

@bot.command(name='play')
async def play(ctx, media_title: str):
    try:
        media_url = plex_client.get_media_url(media_title)
        if not media_url:
            await ctx.send(f"Media '{media_title}' not found.")
            return

        processed_media = await media_processor.process_stream(media_url)
        if not processed_media['success']:
            await ctx.send(f"Error processing media: {processed_media['error']}")
            return

        voice_channel = ctx.author.voice.channel
        if not voice_channel:
            await ctx.send("You need to be in a voice channel to use this command.")
            return

        vc = await voice_channel.connect()
        vc.play(discord.FFmpegPCMAudio(processed_media['path']))
        await ctx.send(f"Now playing: {media_title}")

    except Exception as e:
        logger.error(f"Error in play command: {str(e)}", exc_info=True)
        await ctx.send(f"An error occurred: {str(e)}")

@bot.command(name='stop')
async def stop(ctx):
    try:
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            await ctx.send("Stopped playing.")
        else:
            await ctx.send("Not connected to a voice channel.")
    except Exception as e:
        logger.error(f"Error in stop command: {str(e)}", exc_info=True)
        await ctx.send(f"An error occurred: {str(e)}")

if __name__ == "__main__":
    bot.run(settings.BOT_TOKEN)
