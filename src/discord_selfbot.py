import os
import asyncio
import logging
import discord

# ...existing imports...

logging.basicConfig(level=logging.INFO)
client = discord.Client(intents=discord.Intents.all())

# Read the voice channel ID from env (ensure this variable is set in .env)
VOICE_CHANNEL_ID = int(os.getenv("VOICE_CHANNEL_ID", "0"))

# Enhanced voice playback using robust session management and error handling.
async def initiate_voice_playback(channel, media: str):
    vc = None
    try:
        vc = await channel.connect()
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-i", media, "-f", "s16le", "-ar", "48000", "-ac", "2", "pipe:1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        while True:
            data = await process.stdout.read(4096)
            if not data:
                break  # no more data, exit loop
            await vc.send_audio_packet(data)
        await process.wait()
        logging.info("Playback finished.")
    except Exception as e:
        logging.exception("Voice playback error")
    finally:
        if vc:
            await vc.disconnect()

@client.event
async def on_ready():
    logging.info(f"Selfbot logged in as {client.user}")

@client.event
async def on_message(message):
    # Only respond to DM commands to ensure selfbot safety
    if message.guild is not None: 
        return

    if message.content.startswith("!play"):
        parts = message.content.split(maxsplit=1)
        if len(parts) != 2:
            await message.channel.send("Usage: !play <media_url_or_path>")
            return
        media = parts[1]
        # Use the VOICE_CHANNEL_ID from env
        channel = client.get_channel(VOICE_CHANNEL_ID)
        if not channel or not isinstance(channel, discord.VoiceChannel):
            await message.channel.send("Invalid or misconfigured voice channel.")
            return
        await initiate_voice_playback(channel, media)

if __name__ == "__main__":
    token = os.getenv("DISCORD_SELFBOT_TOKEN")
    if not token:
        logging.error("DISCORD_SELFBOT_TOKEN not set")
        exit(1)
    client.run(token, bot=False)
