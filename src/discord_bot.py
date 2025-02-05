import os
import logging
import asyncio
import discord
from discord.ext import commands
from src.plex_server import PlexServer  # robust Plex integration

# ...existing imports...

# Initialize logging, add production logging level setup here
logging.basicConfig(level=logging.INFO)

# Instantiate bot with command prefix and intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    logging.info(f"Discord Bot logged in as {bot.user}")
    try:
        # Initialize Plex client robustly (using proper env variables and validation)
        plex_url = os.getenv("PLEX_URL")
        plex_token = os.getenv("PLEX_TOKEN")
        if not plex_url or not plex_token:
            raise ValueError("PLEX_URL and PLEX_TOKEN must be set")
        global plex_client
        plex_client = PlexServer(plex_url, plex_token)
    except Exception as e:
        logging.error("Failed to initialize Plex client", exc_info=True)

@bot.event
async def on_command_error(ctx, error):
    logging.error(f"Error in command {ctx.command}: {error}", exc_info=True)
    await ctx.send("❌ An error occurred while processing your command.")

@bot.command(name="play")
async def play_media(ctx, *, media: str):
    try:
        media_info = await asyncio.to_thread(plex_client.search_and_validate, media)
        if not media_info:
            await ctx.send("❌ Media not found.")
            return
        await ctx.send(f"Now playing: {media_info['title']}")
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("❌ You must be in a voice channel to play media.")
            return
        voice_channel = ctx.author.voice.channel
        vc = await voice_channel.connect()
        try:
            audio_source = discord.FFmpegPCMAudio(
                media_info['media_path'],
                executable="ffmpeg",
                before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
            )
            vc.play(audio_source)
            while vc.is_playing():
                await asyncio.sleep(0.5)
        finally:
            await vc.disconnect()
    except Exception:
        logging.exception("Error in play_media command")
        await ctx.send("❌ An error occurred while playing media.")

# ...existing command definitions...

if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        logging.error("DISCORD_BOT_TOKEN not set")
        exit(1)
    bot.run(token)
