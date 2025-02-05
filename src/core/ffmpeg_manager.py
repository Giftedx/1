import asyncio, os, time, signal, logging, psutil
from typing import Dict, Optional, List, AsyncGenerator
from contextlib import asynccontextmanager, suppress
from cachetools import TTLCache  # Ensure this dependency is installed
from prometheus_client import Gauge, Summary
from dataclasses import dataclass
from src.metrics import FFMPEG_ERRORS, STREAM_QUALITY

logger = logging.getLogger(__name__)

FFMPEG_PROCESSES = Gauge('ffmpeg_active_processes', 'Number of active FFmpeg processes')
FFMPEG_CPU_USAGE = Gauge('ffmpeg_cpu_usage_percent', 'FFmpeg CPU usage percentage')
FFMPEG_MEMORY_USAGE = Gauge('ffmpeg_memory_usage_bytes', 'FFmpeg memory usage in bytes')

@dataclass
class FFmpegConfig:
    hwaccel: str = "auto"
    thread_queue_size: int = 512
    preset: str = "veryfast"
    width: int = 1280
    height: int = 720

class StreamingError(Exception):
    pass

class FFmpegManager:
    def __init__(self, config: FFmpegConfig):
        self.config = config
        self._active_processes: Dict[str, asyncio.subprocess.Process] = {}
        self.resource_limits = {"max_cpu_percent": 80.0, "max_memory_mb": 1024, "max_processes": 5}
        self._job_queue = asyncio.PriorityQueue()
        self._shutdown_event = asyncio.Event()
        self._process_duration = Summary('ffmpeg_process_duration_seconds', 'Duration of FFmpeg processes')
        self._stream_cache = TTLCache(maxsize=100, ttl=300)
        self._backoff_factor = 1.0
        self._process_monitor = asyncio.create_task(self._monitor_resources())
        self._error_backoff = 1.0
        self._last_error_time = 0
        self._process_semaphore = asyncio.Semaphore(5)
        self._stream_queue = asyncio.PriorityQueue()
        self._adaptive_quality = True
        self._quality_monitor = asyncio.create_task(self._monitor_stream_quality())
        self._stream_stats = TTLCache(maxsize=100, ttl=300)

    async def _collect_process_stats(self) -> Dict:
        stats = {'cpu_total': 0.0, 'memory_total': 0, 'process_count': len(self._active_processes)}
        for path, proc in list(self._active_processes.items()):
            try:
                process = psutil.Process(proc.pid)
                cpu = process.cpu_percent()
                memory = process.memory_info().rss / 1024 / 1024
                stats['cpu_total'] += cpu
                stats['memory_total'] += memory
            except psutil.NoSuchProcess:
                self._active_processes.pop(path, None)
        return stats

    async def _monitor_resources(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                stats = await self._collect_process_stats()
                # Adaptive limit logic
                if stats['cpu_total'] > self.resource_limits["max_cpu_percent"]:
                    logger.info("High CPU usage; adjusting limits.")
                    self._backoff_factor *= 1.1
                elif stats['cpu_total'] < self.resource_limits["max_cpu_percent"] * 0.7:
                    self._backoff_factor = max(1.0, self._backoff_factor * 0.9)
                adjusted = int(self.resource_limits["max_processes"] / self._backoff_factor)
                self.resource_limits["max_processes"] = max(1, adjusted)
                FFMPEG_PROCESSES.set(stats['process_count'])
                FFMPEG_CPU_USAGE.set(stats['cpu_total'])
                FFMPEG_MEMORY_USAGE.set(stats['memory_total'] * 1024 * 1024)
            except Exception as e:
                logger.error(f"Resource monitoring error: {e}")
            await asyncio.sleep(5)

    async def stream_media(self, media_path: str, quality: str, priority: int = 1) -> AsyncGenerator[None, None]:
        if time.time() - self._last_error_time < self._error_backoff:
            raise StreamingError("Rate limiting active due to recent errors")
        
        try:
            async with self._semaphore:
                command = self._build_optimized_command(media_path, quality)
                process = await self._start_process_with_limits(command)
                yield process
                self._error_backoff = max(1.0, self._error_backoff * 0.9)
        except Exception as e:
            self._last_error_time = time.time()
            self._error_backoff = min(300, self._error_backoff * 2)
            logger.error(f"Streaming error: {e}", exc_info=True)
            raise

    @asynccontextmanager
    async def stream_session(self, media_path: str, quality: str, priority: int = 1):
        command = self._build_optimized_command(media_path, quality)
        process = await self._start_process_with_limits(command)
        try:
            yield process
        except Exception as e:
            logger.error(f"Error in streaming session for {media_path}: {e}", exc_info=True)
            raise
        finally:
            # ...cleanup logic...
            pass

    async def _handle_job(self, job) -> None:
        if self._shutdown_event.is_set():
            return
        if not os.path.exists(job.media_path):
            raise StreamingError(f"Media file '{job.media_path}' does not exist")
        cmd = [
            'ffmpeg',
            '-re',
            '-i', job.media_path,
            '-vf', f'scale={self.config.width}:{self.config.height}',
            '-f', 's16le',
            '-loglevel', 'error',
            self.config.hwaccel
        ]
        start_time = time.time()
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=os.setsid
            )
            self._active_processes[job.media_path] = process
            _, stderr = await process.communicate()
            duration = time.time() - start_time
            self._process_duration.observe(duration)
            if process.returncode != 0:
                logger.error(f"FFmpeg process for {job.media_path} exited with code {process.returncode}: {stderr.decode()}")
                raise StreamingError(f"FFmpeg process failed for {job.media_path}")
        except Exception as e:
            logger.exception(f"Error during FFmpeg execution: {e}")
            FFMPEG_ERRORS.inc()
            raise StreamingError(str(e)) from e
        finally:
            self._active_processes.pop(job.media_path, None)

    async def _start_process_with_limits(self, command: list) -> asyncio.subprocess.Process:
        env = self._prepare_process_environment()
        return await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            limit=32768,
            preexec_fn=lambda: None,  # Replace with real limits if needed.
            env=env
        )

    def _prepare_process_environment(self) -> Dict[str, str]:
        return {
            'FFREPORT': f'file=ffmpeg-{time.time()}.log:level=32',
            'CUDA_VISIBLE_DEVICES': '',
            'FFMPEG_THREADS': '2'
        }

    def _build_optimized_command(self, media_path: str, quality: str) -> list:
        # Enhanced FFmpeg command with better quality and performance
        bitrate = self._get_adaptive_bitrate(quality)
        return [
            'ffmpeg',
            '-hide_banner',
            '-loglevel', 'error',
            '-hwaccel', self.config.hwaccel,
            '-thread_queue_size', str(self.config.thread_queue_size),
            '-i', media_path,
            '-c:v', 'libx264',
            '-preset', self.config.preset,
            '-b:v', bitrate,
            '-maxrate', f"{int(bitrate[:-1]) * 1.5}k",
            '-bufsize', f"{int(bitrate[:-1]) * 2}k",
            '-profile:v', 'high',
            '-level', '4.1',
            '-crf', '23',
            '-movflags', '+faststart',
            '-g', '30',
            '-keyint_min', '30',
            '-sc_threshold', '0',
            '-c:a', 'aac',
            '-b:a', '192k',
            '-ar', '48000',
            '-ac', '2',
            '-f', 'matroska',
            'pipe:1'
        ]

    def _get_adaptive_bitrate(self, quality: str) -> str:
        quality_presets = {
            'low': '1500k',
            'medium': '3000k',
            'high': '5000k'
        }
        return quality_presets.get(quality, '3000k')

    async def create_stream_process(self, url: str, bitrate: int) -> asyncio.subprocess.Process:
        try:
            cmd = self._build_command(url, bitrate)
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            self._active_processes[url] = process
            STREAM_QUALITY.set(bitrate / 1000)  # Convert to kbps
            return process
            
        except Exception as e:
            FFMPEG_ERRORS.inc()
            logger.error(f"FFmpeg process creation failed: {e}")
            raise

    def _build_command(self, url: str, bitrate: int) -> list[str]:
        return [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-hwaccel", self.config.hwaccel,
            "-thread_queue_size", str(self.config.thread_queue_size),
            "-i", url,
            "-c:v", "libx264",
            "-preset", self.config.preset,
            "-b:v", f"{bitrate}k",
            "-c:a", "aac",
            "-b:a", "128k",
            "-f", "matroska",
            "-"
        ]

    async def stop_stream(self, media_path: str) -> None:
        if media_path in self._active_processes:
            process = self._active_processes[media_path]
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            self._active_processes.pop(media_path, None)
        else:
            logger.warning(f"No active FFmpeg process found for {media_path}.")

    async def stop_stream(self, url: str) -> None:
        if url in self._active_processes:
            process = self._active_processes[url]
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                process.kill()
            finally:
                del self._active_processes[url]

    async def cleanup(self) -> None:
        self._shutdown_event.set()
        tasks = [self.stop_stream(media) for media in list(self._active_processes.keys())]
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Cleaned up all FFmpeg processes.")

    async def _monitor_stream_quality(self):
        while not self._shutdown_event.is_set():
            for path, stats in self._stream_stats.items():
                if stats['errors'] > 3:
                    await self._adjust_stream_quality(path)
            await asyncio.sleep(10)