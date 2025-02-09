import os
import asyncio
import logging
import discord
from functools import partial
from discord.ext import commands
from src.core.ffmpeg_manager import FFmpegManager
from src.core.config import settings
from src.core.exceptions import StreamingError, MediaNotFoundError
from src.monitoring.metrics import stream_metrics, STREAM_LATENCY

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.voice_states = True
intents.messages = True  # Ensure message intents enabled

class SelfBot(commands.Bot):
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
        logging.info(f"Selfbot logged in as {self.user}")
        try:
            if self._voice_channel_id:
                await self.join_voice(self._voice_channel_id)
        except Exception as e:
            logger.error(f"Voice join failed: {e}", exc_info=True)

    async def on_message(self, message: discord.Message):
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
            if self._voice_channel_id is None:
                await message.channel.send("VOICE_CHANNEL_ID is not configured correctly.")
                return
            channel = self.get_channel(self._voice_channel_id)
            if not channel or not isinstance(channel, discord.VoiceChannel):
                await message.channel.send("Invalid or misconfigured voice channel.")
                return
            await self.initiate_voice_playback(channel, media)

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

    async def initiate_voice_playback(self, channel, media: str):
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
            logger.info("Playback finished.")
        except Exception as e:
            logger.exception("Voice playback error")
        finally:
            if vc:
                await vc.disconnect()

async def main():
    ffmpeg_manager = FFmpegManager(
        virtual_cam=settings.VIRTUAL_CAM_DEVICE,
        video_width=settings.VIDEO_WIDTH,
        video_height=settings.VIDEO_HEIGHT,
        loglevel=settings.FFMPEG_LOGLEVEL
    )
    bot = SelfBot(command_prefix='!', self_bot=True, ffmpeg_manager=ffmpeg_manager)
    token = os.getenv("STREAMING_BOT_TOKEN")
    if not token:
        logger.error("STREAMING_BOT_TOKEN not set in environment.")
        return
    await bot.start(token, bot=False)

if __name__ == "__main__":
    asyncio.run(main())
