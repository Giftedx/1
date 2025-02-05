import asyncio
import logging
from typing import Optional
import ffmpeg
from src.core.ffmpeg_manager import FFmpegManager
from src.metrics import MEDIA_STREAMS, STREAM_ERRORS

logger = logging.getLogger(__name__)

class MediaPlayer:
    def __init__(self, ffmpeg_manager: FFmpegManager):
        self.ffmpeg = ffmpeg_manager
        self._current_process: Optional[asyncio.subprocess.Process] = None
        self._stream_task: Optional[asyncio.Task] = None

    async def play(self, stream_url: str, voice_channel) -> None:
        if self._current_process:
            await self.stop()

        try:
            MEDIA_STREAMS.inc()
            process = await self.ffmpeg.create_stream_process(
                stream_url,
                voice_channel.bitrate
            )
            self._current_process = process
            self._stream_task = asyncio.create_task(self._stream_monitor())
            
        except Exception as e:
            STREAM_ERRORS.inc()
            logger.error(f"Failed to start media playback: {e}")
            raise

    async def stop(self) -> None:
        if self._stream_task:
            self._stream_task.cancel()
            
        if self._current_process:
            try:
                self._current_process.terminate()
                await self._current_process.wait()
            except Exception as e:
                logger.error(f"Error stopping playback: {e}")
            finally:
                self._current_process = None
                MEDIA_STREAMS.dec()

    async def _stream_monitor(self) -> None:
        if not self._current_process:
            return

        try:
            await self._current_process.wait()
        except asyncio.CancelledError:
            await self.stop()
        except Exception as e:
            logger.error(f"Stream monitor error: {e}")
            STREAM_ERRORS.inc()
            await self.stop()
