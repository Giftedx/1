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
        if not self.voice_client:
            logger.info("No active voice connection; attempting to join.")
            await self.join_voice(channel_id=self._voice_channel_id or 1234567890)
            if not self.voice_client:
                logger.error("Unable to join voice channel; aborting playback.")
                return
        try:
            audio_source = discord.FFmpegPCMAudio(
                media_path,
                executable="ffmpeg",
                before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
            )
            self.voice_client.play(audio_source)
            while self.voice_client.is_playing():
                await asyncio.sleep(0.5)
            logger.info("Media streaming completed.")
        except Exception as e:
            logger.error(f"Error during media streaming: {e}", exc_info=True)
        finally:
            await self.leave_voice()

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
