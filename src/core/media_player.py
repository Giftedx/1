import asyncio
import logging
from typing import Optional, Dict
from dataclasses import dataclass
from src.core.ffmpeg_manager import FFmpegManager
from src.core.exceptions import StreamingError
from src.monitoring.metrics import stream_metrics

logger = logging.getLogger(__name__)

@dataclass
class StreamConfig:
    quality: str = "medium"
    max_retries: int = 3
    retry_delay: float = 2.0
    timeout: float = 30.0

class MediaPlayer:
    def __init__(self, ffmpeg_manager: FFmpegManager):
        self.ffmpeg = ffmpeg_manager
        self._current_process: Optional[asyncio.subprocess.Process] = None
        self._stream_lock = asyncio.Lock()
        self._active_streams: Dict[str, asyncio.Task] = {}
        self._stream_configs: Dict[str, StreamConfig] = {}
        self._max_streams = 5

    async def play(self, stream_url: str, voice_channel, config: Optional[StreamConfig] = None) -> None:
        """Start playing media with proper error handling and cleanup."""
        config = config or StreamConfig()
        
        if self._current_process:
            await self.stop()

        if len(self._active_streams) >= self._max_streams:
            raise StreamingError("Maximum concurrent streams reached")

        async with self._stream_lock:
            try:
                process = await self.ffmpeg.create_stream_process(
                    stream_url,
                    voice_channel.bitrate
                )
                self._current_process = process
                
                # Monitor the stream in a separate task
                task = asyncio.create_task(
                    self._monitor_stream(stream_url, process, config)
                )
                self._active_streams[stream_url] = task
                self._stream_configs[stream_url] = config
                
                stream_metrics.active_streams.inc()
                
            except Exception as e:
                logger.error(f"Failed to start playback: {e}", exc_info=True)
                stream_metrics.stream_errors.inc()
                raise StreamingError(f"Failed to start playback: {str(e)}")

    async def stop(self) -> None:
        """Stop playback and clean up resources."""
        async with self._stream_lock:
            if self._current_process:
                try:
                    self._current_process.terminate()
                    await asyncio.wait_for(
                        self._current_process.wait(),
                        timeout=5.0
                    )
                except asyncio.TimeoutError:
                    self._current_process.kill()
                except Exception as e:
                    logger.error(f"Error stopping playback: {e}")
                finally:
                    self._current_process = None
                    stream_metrics.active_streams.dec()

            # Cancel any monitoring tasks
            tasks = list(self._active_streams.values())
            self._active_streams.clear()
            self._stream_configs.clear()
            
            for task in tasks:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def _monitor_stream(self, 
                            stream_url: str, 
                            process: asyncio.subprocess.Process,
                            config: StreamConfig) -> None:
        """Monitor stream process and handle failures."""
        retries = 0
        
        while retries < config.max_retries:
            try:
                await asyncio.wait_for(
                    process.wait(),
                    timeout=config.timeout
                )
                
                if process.returncode == 0:
                    logger.info(f"Stream completed successfully: {stream_url}")
                    break
                    
                logger.warning(
                    f"Stream process exited with code {process.returncode}: {stream_url}"
                )
                retries += 1
                
                if retries < config.max_retries:
                    await asyncio.sleep(config.retry_delay * retries)
                    process = await self.ffmpeg.create_stream_process(
                        stream_url,
                        self._current_bitrate
                    )
                    
            except asyncio.TimeoutError:
                logger.warning(f"Stream timeout: {stream_url}")
                retries += 1
                continue
                
            except asyncio.CancelledError:
                logger.info(f"Stream cancelled: {stream_url}")
                break
                
            except Exception as e:
                logger.error(f"Stream error: {e}", exc_info=True)
                stream_metrics.stream_errors.inc()
                break
                
        if retries >= config.max_retries:
            logger.error(f"Max retries reached for stream: {stream_url}")
            stream_metrics.stream_errors.inc()
