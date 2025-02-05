import os
import asyncio
import logging
import discord
from functools import partial
from discord.ext import commands
from src.core.ffmpeg_manager import FFmpegManager
from src.utils.config import settings
from src.core.exceptions import StreamingError, MediaNotFoundError
from src.monitoring.metrics import stream_metrics, STREAM_LATENCY

logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.voice_states = True
intents.messages = True  # Ensure message intents enabled

class SelfBotClient(discord.Client):
    def __init__(self, ffmpeg_manager: FFmpegManager, *args, **kwargs):
        super().__init__(*args, intents=intents, **kwargs)
        self.ffmpeg_manager = ffmpeg_manager
        self.voice_client: discord.VoiceClient = None
        self._voice_channel_id: int = int(os.getenv("VOICE_CHANNEL_ID", "0"))
        self._stream_retries = {}
        self._max_retries = 3
        self._retry_delay = 2.0
        self._voice_states = {}
        self._reconnect_attempts = {}
        self._active_streams = 0
        self._max_streams = settings.MAX_CONCURRENT_STREAMS

    async def on_ready(self):
        logger.info(f"Selfbot logged in as {self.user}")
        try:
            if self._voice_channel_id:
                await self.join_voice(self._voice_channel_id)
        except Exception as e:
            logger.error(f"Voice join failed: {e}", exc_info=True)

    async def on_message(self, message: discord.Message):
        # Basic command for playback
        if message.content.startswith("!playself"):
            media_path = message.content.replace("!playself", "").strip()
            await self.play_media_in_voice(media_path)

    @stream_metrics.count_exceptions()
    @stream_metrics.time()
    async def join_voice(self, channel_id: int):
        try:
            channel = self.get_channel(channel_id)
            if not channel or not isinstance(channel, discord.VoiceChannel):
                raise StreamingError("Specified channel is invalid.")
            if self.voice_client and self.voice_client.is_connected():
                await self.voice_client.move_to(channel)
            else:
                self.voice_client = await channel.connect(timeout=20.0, reconnect=True)
            logger.info(f"Connected to voice channel: {channel.name}")
        except Exception as e:
            logger.error(f"Failed to join voice channel: {e}", exc_info=True)
            raise StreamingError(f"Voice channel connection failed: {str(e)}")

    async def leave_voice(self):
        if self.voice_client:
            await self.voice_client.disconnect()
            logger.info("Left voice channel.")

    @stream_metrics.count_exceptions()
    @stream_metrics.time()
    async def play_media_in_voice(self, media_path: str, quality: str = "medium"):
        if self._active_streams >= self._max_streams:
            raise StreamingError("Maximum concurrent streams reached")

        if not self.voice_client or not self.voice_client.is_connected():
            await self.join_voice(self._voice_channel_id)

        try:
            # Configure FFmpeg with optimized settings
            options = self.ffmpeg_manager.get_stream_options(
                width=settings.VIDEO_WIDTH,
                height=settings.VIDEO_HEIGHT,
                preset=settings.FFMPEG_PRESET,
                hwaccel=settings.FFMPEG_HWACCEL
            )

            with STREAM_LATENCY.time():
                source = discord.FFmpegPCMAudio(
                    media_path,
                    executable=self.ffmpeg_manager.ffmpeg_path,
                    **options
                )
                
                self._active_streams += 1
                self.voice_client.play(
                    source,
                    after=partial(self._on_playback_complete, media_path)
                )
                logger.info(f"Started streaming: {media_path}")

        except Exception as e:
            logger.error(f"Playback error: {e}", exc_info=True)
            self._active_streams = max(0, self._active_streams - 1)
            if isinstance(e, StreamingError):
                raise
            raise StreamingError(f"Playback failed: {str(e)}")

    def _on_playback_complete(self, media_path: str, error=None):
        self._active_streams = max(0, self._active_streams - 1)
        if error:
            logger.error(f"Playback error for {media_path}: {error}")
        else:
            logger.info(f"Completed streaming: {media_path}")

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
    logging.basicConfig(level=logging.INFO)
    ffmpeg_manager = FFmpegManager(
        virtual_cam=settings.VIRTUAL_CAM_DEVICE,
        video_width=settings.VIDEO_WIDTH,
        video_height=settings.VIDEO_HEIGHT,
        loglevel=settings.FFMPEG_LOGLEVEL
    )
    client = SelfBotClient(ffmpeg_manager)
    token = os.getenv("STREAMING_BOT_TOKEN")
    if not token:
        logger.error("STREAMING_BOT_TOKEN not set in environment.")
        return
    client.run(token, bot=False)

if __name__ == "__main__":
    main()
