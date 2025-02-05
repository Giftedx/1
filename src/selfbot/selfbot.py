import os
import asyncio
import logging
import discord
from discord.ext import tasks
from src.core.ffmpeg_manager import FFmpegManager
from src.utils.config import settings

logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.voice_states = True
intents.messages = True  # Ensure message intents enabled

class SelfBotClient(discord.Client):
    def __init__(self, ffmpeg_manager: FFmpegManager, *args, **kwargs):
        super().__init__(*args, intents=intents, **kwargs)
        self.ffmpeg_manager = ffmpeg_manager
        self.voice_client = None
        self._voice_channel_id = None  # Set or update as needed
        self._stream_retries = {}
        self._max_retries = 3
        self._retry_delay = 2.0
        self._voice_states = {}
        self._reconnect_attempts = {}

    async def on_ready(self):
        logger.info(f"Selfbot logged in as {self.user}")

    async def on_message(self, message):
        # Only handle DM commands
        if message.guild is not None:
            return
        if message.content.startswith("!play"):
            parts = message.content.split(maxsplit=1)
            if len(parts) != 2:
                await message.channel.send("Usage: !play <media_path>")
                return
            media = parts[1]
            if not self._voice_channel_id:
                await message.channel.send("Voice channel not configured.")
                return
            channel = self.get_channel(self._voice_channel_id)
            if not channel or not isinstance(channel, discord.VoiceChannel):
                await message.channel.send("Invalid voice channel configuration.")
                return
            await self.play_media_in_voice(media)

    async def join_voice(self, channel_id: int):
        channel = self.get_channel(channel_id)
        if channel and isinstance(channel, discord.VoiceChannel):
            for attempt in range(3):
                try:
                    self.voice_client = await channel.connect()
                    logger.info(f"Joined voice channel: {channel.name}")
                    return
                except Exception as e:
                    logger.error(f"Attempt {attempt+1}: Failed to join voice channel: {e}", exc_info=True)
                    await asyncio.sleep(2)
            logger.error("Could not join the voice channel after multiple attempts.")
        else:
            logger.error("Invalid voice channel specified.")

    async def leave_voice(self):
        if self.voice_client:
            await self.voice_client.disconnect()
            logger.info("Left voice channel.")

    async def play_media_in_voice(self, media_path: str, quality: str = "medium"):
        try:
            if not self.voice_client:
                await self._ensure_voice_connection()
            
            stream_options = {
                'before_options': (
                    '-reconnect 1 -reconnect_streamed 1 '
                    '-reconnect_delay_max 5 -nostdin'
                ),
                'options': (
                    '-vn -b:a 192k -bufsize 4096k '
                    '-ac 2 -ar 48000'
                )
            }
            
            audio_source = discord.FFmpegPCMAudio(
                media_path,
                executable="ffmpeg",
                **stream_options
            )
            
            self.voice_client.play(
                discord.PCMVolumeTransformer(audio_source, volume=1.0),
                after=lambda e: self._handle_playback_completed(e, media_path)
            )
        except Exception as e:
            logger.error(f"Playback error: {e}", exc_info=True)
            await self._handle_playback_error(e, media_path)

    async def _ensure_voice_connection(self):
        try:
            channel = self.get_channel(self._voice_channel_id)
            if not channel:
                raise ValueError("Invalid voice channel")
            self.voice_client = await channel.connect(timeout=20.0, reconnect=True)
            self.voice_client.pause()  # Ensure clean state
            await asyncio.sleep(0.5)  # Brief pause to stabilize
            self.voice_client.resume()
        except Exception as e:
            logger.error(f"Voice connection error: {e}", exc_info=True)
            raise

def main():
    from src.core.ffmpeg_manager import FFmpegManager  # Import here if necessary
    ffmpeg_manager = FFmpegManager(
        virtual_cam=settings.VIRTUAL_CAM_DEVICE,
        video_width=settings.VIDEO_WIDTH,
        video_height=settings.VIDEO_HEIGHT,
        loglevel=settings.FFMPEG_LOGLEVEL
    )
    client = SelfBotClient(ffmpeg_manager)
    client._voice_channel_id = 1234567890  # Update with a valid channel id
    token = os.getenv("DISCORD_SELFBOT_TOKEN")
    if not token:
        logger.error("DISCORD_SELFBOT_TOKEN not set")
        exit(1)
    client.run(token)

if __name__ == "__main__":
    main()
