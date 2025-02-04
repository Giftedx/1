import asyncio
import logging
import os
import time
import signal
from typing import Dict, Optional, List, AsyncGenerator
import psutil
from prometheus_client import Gauge, Summary
from dataclasses import dataclass, field
from asyncio import Queue, PriorityQueue
from src.monitoring.metrics import CPU_USAGE, MEMORY_USAGE
from src.core.worker_pool import WorkerPool, WorkerConfig
from contextlib import asynccontextmanager
from src.core.memory_manager import MemoryManager, MemoryThresholds
from src.utils.process_pool import ProcessPool

logger = logging.getLogger(__name__)

FFMPEG_PROCESSES = Gauge('ffmpeg_active_processes', 'Number of active FFmpeg processes')
FFMPEG_CPU_USAGE = Gauge('ffmpeg_cpu_usage_percent', 'FFmpeg CPU usage percentage')
FFMPEG_MEMORY_USAGE = Gauge('ffmpeg_memory_usage_bytes', 'FFmpeg memory usage in bytes')

@dataclass(order=True)
class FFmpegJob:
    priority: int
    media_path: str
    quality: str
    timestamp: float = field(default_factory=time.time)

@dataclass
class ResourceLimits:
    max_cpu_percent: float = 80.0
    max_memory_mb: int = 1024
    max_processes: int = 5

class StreamingError(Exception):
    """Exception raised for errors in the media streaming process."""
    pass

class FFmpegManager:
    """
    Handles FFmpeg streaming processes.
    """
    def __init__(self, virtual_cam: str, video_width: int, video_height: int, loglevel: str,
                 resource_limits: Optional[ResourceLimits] = None) -> None:
        """
        Initializes the FFmpegManager with the given parameters.

        :param virtual_cam: The virtual camera device to stream to.
        :param video_width: The width of the video stream.
        :param video_height: The height of the video stream.
        :param loglevel: The log level for FFmpeg.
        """
        self.virtual_cam = virtual_cam
        self.video_width = video_width
        self.video_height = video_height
        self.loglevel = loglevel
        self.active_processes: Dict[str, asyncio.subprocess.Process] = {}
        self._monitor_task: Optional[asyncio.Task] = None
        self.resource_limits = resource_limits or ResourceLimits()
        self._process_stats: Dict[str, Dict] = {}
        self._adaptive_limits = True
        self._backoff_factor = 1.0
        self._job_queue: PriorityQueue[FFmpegJob] = PriorityQueue()
        self._worker_task: Optional[asyncio.Task] = None
        self._max_workers = 3
        self._worker_pool = WorkerPool(WorkerConfig(max_workers=self._max_workers))
        self._memory_manager = MemoryManager(MemoryThresholds())
        self._memory_manager.set_warning_callback(self._handle_memory_warning)
        self._memory_manager.set_critical_callback(self._handle_memory_critical)
        self._shutdown_event = asyncio.Event()
        self._process_cleanup_tasks: List[asyncio.Task] = []
        self._process_duration = Summary('ffmpeg_process_duration_seconds',
                                       'Duration of FFmpeg processes')
        self._process_pool = ProcessPool(max_size=self.resource_limits.max_processes)
        self._stream_cache = TTLCache(maxsize=100, ttl=300)
        self._adaptive_quality = AdaptiveQuality(
            min_quality=20,
            max_quality=28,
            target_cpu=70.0
        )
        self._process_scheduler = ProcessScheduler(
            max_concurrent=self.resource_limits.max_processes,
            priority_levels=3
        )
        self._performance_monitor = PerformanceMonitor(
            warning_threshold=70.0,
            critical_threshold=90.0
        )
        self._process_monitor = ProcessMonitor(
            check_interval=5.0,
            metrics_callback=self._update_process_metrics
        )
        self._transcoding_pipeline = TranscodingPipeline(
            preset_configs=self._load_transcoding_presets(),
            hardware_acceleration=True
        )

    async def _adjust_resource_limits(self, stats: Dict) -> None:
        if not self._adaptive_limits:
            return

        cpu_usage = stats['cpu_total']
        if cpu_usage > self.resource_limits.max_cpu_percent:
            self._backoff_factor *= 1.5
        elif cpu_usage < self.resource_limits.max_cpu_percent * 0.7:
            self._backoff_factor = max(1.0, self._backoff_factor * 0.8)

        adjusted_limit = int(self.resource_limits.max_processes / self._backoff_factor)
        self.resource_limits.max_processes = max(1, adjusted_limit)

    async def _monitor_resources(self) -> None:
        while True:
            try:
                stats = await self._collect_process_stats()
                await self._adjust_resource_limits(stats)
                if await self._check_resource_limits(stats):
                    logger.warning("Resource limits exceeded, throttling new processes")
                self._update_metrics(stats)
                
                # Update global metrics
                CPU_USAGE.set(stats['cpu_total'])
                MEMORY_USAGE.set(stats['memory_total'] * 1024 * 1024)
                
            except Exception as e:
                logger.error(f"Resource monitoring error: {e}")
            await asyncio.sleep(5)

    async def _collect_process_stats(self) -> Dict:
        stats = {'cpu_total': 0.0, 'memory_total': 0, 'process_count': len(self.active_processes)}
        for path, proc in self.active_processes.items():
            try:
                process = psutil.Process(proc.pid)
                cpu = process.cpu_percent()
                memory = process.memory_info().rss / 1024 / 1024  # Convert to MB
                stats['cpu_total'] += cpu
                stats['memory_total'] += memory
                self._process_stats[path] = {'cpu': cpu, 'memory': memory}
            except psutil.NoSuchProcess:
                self._process_stats.pop(path, None)
        return stats

    async def _check_resource_limits(self, stats: Dict) -> bool:
        return (stats['cpu_total'] > self.resource_limits.max_cpu_percent or
                stats['memory_total'] > self.resource_limits.max_memory_mb or
                stats['process_count'] > self.resource_limits.max_processes)

    def _update_metrics(self, stats: Dict) -> None:
        FFMPEG_PROCESSES.set(stats['process_count'])
        FFMPEG_CPU_USAGE.set(stats['cpu_total'])
        FFMPEG_MEMORY_USAGE.set(stats['memory_total'] * 1024 * 1024)  # Convert MB to bytes

    async def start_monitoring(self) -> None:
        if not self._monitor_task:
            self._monitor_task = asyncio.create_task(self._monitor_resources())

    async def start(self) -> None:
        """Start the FFmpeg manager workers."""
        await self._worker_pool.start_worker("job_processor", self._process_jobs)
        await self._worker_pool.start_worker("resource_monitor", self._monitor_resources)
        await self._memory_manager.start_monitoring()

    async def _process_jobs(self) -> None:
        while True:
            try:
                job = await self._job_queue.get()
                if await self._can_start_process():
                    asyncio.create_task(self._handle_job(job))
                else:
                    await self._job_queue.put(job)
                    await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Error processing FFmpeg job: {e}", exc_info=True)

    async def _can_start_process(self) -> bool:
        stats = await self._collect_process_stats()
        return not await self._check_resource_limits(stats)

    async def stream_media(self, media_path: str, quality: str, priority: int = 1) -> AsyncGenerator[None, None]:
        cache_key = f"{media_path}:{quality}"
        if cached_stream := self._stream_cache.get(cache_key):
            return cached_stream

        process_slot = await self._process_scheduler.acquire(priority)
        try:
            command = self._build_optimized_command(media_path, quality)
            process = await self._start_process_with_limits(command)
            yield process
        finally:
            self._process_scheduler.release(process_slot)

    @asynccontextmanager
    async def stream_session(self, media_path: str, quality: str, priority: int = 1):
        """Async context manager for streaming sessions."""
        try:
            await self.stream_media(media_path, quality, priority)
            yield
        finally:
            await self.stop_stream(media_path)

    async def _handle_job(self, job: FFmpegJob) -> None:
        if self._shutdown_event.is_set():
            return

        media_path = job.media_path
        quality = job.quality
        if not os.path.exists(media_path):
            raise StreamingError(f"Media file '{media_path}' does not exist")
            
        cmd = [
            'ffmpeg',
            '-re',
            '-i', media_path,
            '-vf', f'scale={self.video_width}:{self.video_height}',
            '-f', 'v4l2',
            '-loglevel', self.loglevel,
            self.virtual_cam
        ]
        logger.info(f"Starting FFmpeg process for {media_path} with quality {quality}.")
        start_time = time.time()
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=os.setsid,  # Create new process group
                limit=32768  # Limit buffer size
            )
            
            cleanup_task = asyncio.create_task(self._monitor_process(process, media_path))
            self._process_cleanup_tasks.append(cleanup_task)
            
            _, stderr = await process.communicate()  # Only capture stderr
            if process.returncode != 0:
                logger.error(f"FFmpeg process for {media_path} failed with return code {process.returncode}.")
                logger.error(stderr.decode())
                raise StreamingError(f"FFmpeg process failed for {media_path}")
            duration = time.time() - start_time
            logger.info(f"FFmpeg process for {media_path} finished in {duration:.2f} seconds.")
        except Exception as e:
            logger.exception(f"Error during FFmpeg execution: {e}")
            raise StreamingError(f"FFmpeg process failed: {str(e)}") from e
        finally:
            self._process_cleanup_tasks = [t for t in self._process_cleanup_tasks if not t.done()]

    async def _start_process(self, command: List[str]) -> asyncio.subprocess.Process:
        return await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            limit=32768,
            preexec_fn=lambda: os.setpriority(os.PRIO_PROCESS, 0, 10)
        )

    async def _start_process_with_limits(self, command: List[str]) -> asyncio.subprocess.Process:
        resource_limits = await self._calculate_resource_limits()
        env = self._prepare_process_environment()
        
        return await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            limit=32768,
            preexec_fn=lambda: self._apply_process_limits(resource_limits),
            env=env
        )

    def _prepare_process_environment(self) -> Dict[str, str]:
        return {
            'FFREPORT': f'file=ffmpeg-{time.time()}.log:level=32',
            'CUDA_VISIBLE_DEVICES': self._get_available_gpu(),
            'FFMPEG_THREADS': str(self._calculate_optimal_threads())
        }

    async def _monitor_process(self, process: asyncio.subprocess.Process, media_path: str) -> None:
        """Monitor a single FFmpeg process."""
        start_time = time.monotonic()
        try:
            await process.wait()
        finally:
            duration = time.monotonic() - start_time
            self._process_duration.observe(duration)
            self.active_processes.pop(media_path, None)
            self._update_process_metrics()

    async def _update_process_metrics(self) -> None:
        stats = await self._collect_process_stats()
        FFMPEG_PROCESSES.set(stats['process_count'])
        if stats['process_count'] > 0:
            FFMPEG_CPU_USAGE.set(stats['cpu_total'] / stats['process_count'])

    async def stop_stream(self, media_path: str) -> None:
        if media_path in self.active_processes:
            process = self.active_processes[media_path]
            logger.info(f"Stopping FFmpeg process for {media_path}.")
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(f"FFmpeg process for {media_path} did not terminate gracefully; killing.")
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            self.active_processes.pop(media_path, None)
        else:
            logger.warning(f"No active FFmpeg process found for {media_path}.")

    async def cleanup(self) -> None:
        self._shutdown_event.set()
        await self._memory_manager.cleanup()
        await self._worker_pool.shutdown()
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        tasks = [self.stop_stream(media) for media in list(self.active_processes.keys())]
        await asyncio.gather(*tasks, return_exceptions=True)
        cleanup_tasks = [t for t in self._process_cleanup_tasks if not t.done()]
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        logger.info("Cleaned up all FFmpeg processes.")

    async def _handle_memory_warning(self) -> None:
        logger.warning("Memory usage high, throttling new processes")
        self._backoff_factor *= 1.5

    async def _handle_memory_critical(self) -> None:
        logger.critical("Memory usage critical, stopping new processes")
        lowest_priority_job = None
        while not self._job_queue.empty():
            job = await self._job_queue.get()
            if not lowest_priority_job or job.priority > lowest_priority_job.priority:
                lowest_priority_job = job
        if lowest_priority_job:
            await self.stop_stream(lowest_priority_job.media_path)