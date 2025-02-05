import asyncio, os, time, signal, logging, psutil
from typing import Dict, Optional, List, AsyncGenerator
from contextlib import asynccontextmanager, suppress
from cachetools import TTLCache  # Ensure this dependency is installed
from prometheus_client import Gauge, Summary
# ...additional imports for adaptive quality etc.

logger = logging.getLogger(__name__)

FFMPEG_PROCESSES = Gauge('ffmpeg_active_processes', 'Number of active FFmpeg processes')
FFMPEG_CPU_USAGE = Gauge('ffmpeg_cpu_usage_percent', 'FFmpeg CPU usage percentage')
FFMPEG_MEMORY_USAGE = Gauge('ffmpeg_memory_usage_bytes', 'FFmpeg memory usage in bytes')

class StreamingError(Exception):
    pass

class FFmpegManager:
    def __init__(self, virtual_cam: str, video_width: int, video_height: int, loglevel: str,
                 resource_limits: Optional[dict] = None) -> None:
        self.virtual_cam = virtual_cam
        self.video_width = video_width
        self.video_height = video_height
        self.loglevel = loglevel
        self.active_processes: Dict[str, asyncio.subprocess.Process] = {}
        self.resource_limits = resource_limits or {"max_cpu_percent": 80.0, "max_memory_mb": 1024, "max_processes": 5}
        self._job_queue = asyncio.PriorityQueue()
        self._shutdown_event = asyncio.Event()
        self._process_duration = Summary('ffmpeg_process_duration_seconds', 'Duration of FFmpeg processes')
        self._stream_cache = TTLCache(maxsize=100, ttl=300)
        self._backoff_factor = 1.0

    async def _collect_process_stats(self) -> Dict:
        stats = {'cpu_total': 0.0, 'memory_total': 0, 'process_count': len(self.active_processes)}
        for path, proc in list(self.active_processes.items()):
            try:
                process = psutil.Process(proc.pid)
                cpu = process.cpu_percent()
                memory = process.memory_info().rss / 1024 / 1024
                stats['cpu_total'] += cpu
                stats['memory_total'] += memory
            except psutil.NoSuchProcess:
                self.active_processes.pop(path, None)
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
        cache_key = f"{media_path}:{quality}"
        if cached_stream := self._stream_cache.get(cache_key):
            yield from cached_stream
            return
        # Acquire a processing slot; placeholder for scheduler logic.
        command = self._build_optimized_command(media_path, quality)
        process = await self._start_process_with_limits(command)
        try:
            yield process
        finally:
            # Release scheduler slot as needed.
            pass

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
            '-vf', f'scale={self.video_width}:{self.video_height}',
            '-f', 's16le',
            '-loglevel', self.loglevel,
            self.virtual_cam
        ]
        start_time = time.time()
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=os.setsid
            )
            self.active_processes[job.media_path] = process
            _, stderr = await process.communicate()
            duration = time.time() - start_time
            self._process_duration.observe(duration)
            if process.returncode != 0:
                logger.error(f"FFmpeg process for {job.media_path} exited with code {process.returncode}: {stderr.decode()}")
                raise StreamingError(f"FFmpeg process failed for {job.media_path}")
        except Exception as e:
            logger.exception(f"Error during FFmpeg execution: {e}")
            raise StreamingError(str(e)) from e
        finally:
            self.active_processes.pop(job.media_path, None)

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
        bitrate = "1500k" if quality == "medium" else "3000k"
        return [
            'ffmpeg',
            '-re',
            '-i', media_path,
            '-b:v', bitrate,
            '-vf', f'scale={self.video_width}:{self.video_height}',
            '-f', 's16le',
            'pipe:1'
        ]

    async def stop_stream(self, media_path: str) -> None:
        if media_path in self.active_processes:
            process = self.active_processes[media_path]
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            self.active_processes.pop(media_path, None)
        else:
            logger.warning(f"No active FFmpeg process found for {media_path}.")

    async def cleanup(self) -> None:
        self._shutdown_event.set()
        tasks = [self.stop_stream(media) for media in list(self.active_processes.keys())]
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Cleaned up all FFmpeg processes.")