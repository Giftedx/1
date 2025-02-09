import asyncio, os, time, signal, logging, psutil, platform, subprocess
from typing import Dict, Optional, List, AsyncGenerator
from contextlib import asynccontextmanager
from cachetools import TTLCache
from prometheus_client import Gauge, Summary
from dataclasses import dataclass
from src.metrics import FFMPEG_ERRORS, STREAM_QUALITY
from src.utils.config import settings
from src.core.exceptions import StreamingError
from src.monitoring.metrics import FFMPEG_LATENCY, TRANSCODE_DURATION

logger = logging.getLogger(__name__)

FFMPEG_PROCESSES = Gauge('ffmpeg_active_processes', 'Number of active FFmpeg processes')
FFMPEG_CPU_USAGE = Gauge('ffmpeg_cpu_usage_percent', 'FFmpeg CPU usage percentage')
FFMPEG_MEMORY_USAGE = Gauge('ffmpeg_memory_usage_bytes', 'FFmpeg memory usage in bytes')

@dataclass
class FFmpegConfig:
    thread_queue_size: int = 512
    hwaccel: str = "auto"
    preset: str = "veryfast"
    width: int = 1280
    height: int = 720
    audio_bitrate: str = "192k"
    video_bitrate: str = "3000k"
    threads: int = 4

class FFmpegManager:
    def __init__(self):
        self.ffmpeg_path = self._find_ffmpeg()
        self.config = FFmpegConfig(
            thread_queue_size=settings.FFMPEG_THREAD_QUEUE_SIZE,
            hwaccel=settings.FFMPEG_HWACCEL,
            preset=settings.FFMPEG_PRESET,
            width=settings.VIDEO_WIDTH,
            height=settings.VIDEO_HEIGHT
        )
        self._verify_ffmpeg()
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
        self._bitrate_controller = PIDController(
            Kp=1.0,
            Ki=0.1,
            Kd=0.01,
            setpoint=bitrate
        )

    def _find_ffmpeg(self) -> str:
        """Locate FFmpeg binary with fallback options."""
        paths = [
            "ffmpeg",
            "/usr/bin/ffmpeg",
            "/usr/local/bin/ffmpeg",
            "C:\\ffmpeg\\bin\\ffmpeg.exe" if platform.system() == "Windows" else None
        ]
        
        for path in filter(None, paths):
            try:
                subprocess.run([path, "-version"], capture_output=True, check=True)
                return path
            except (subprocess.SubProcessError, FileNotFoundError):
                continue
                
        raise StreamingError("FFmpeg not found. Please install FFmpeg.")

    def _verify_ffmpeg(self) -> None:
        """Verify FFmpeg installation and capabilities."""
        try:
            result = subprocess.run(
                [self.ffmpeg_path, "-version"],
                capture_output=True,
                text=True,
                check=True
            )
            logger.info(f"FFmpeg version: {result.stdout.splitlines()[0]}")
            
            # Check hardware acceleration support
            if self.config.hwaccel != "none":
                self._check_hwaccel()
                
        except subprocess.SubProcessError as e:
            raise StreamingError(f"FFmpeg verification failed: {str(e)}")

    def _check_hwaccel(self) -> None:
        """Check hardware acceleration support."""
        try:
            result = subprocess.run(
                [self.ffmpeg_path, "-hwaccels"],
                capture_output=True,
                text=True,
                check=True
            )
            available_hwaccels = result.stdout.strip().split('\n')[1:]
            logger.info(f"Available hardware accelerators: {', '.join(available_hwaccels)}")
            
            if self.config.hwaccel != "auto" and self.config.hwaccel not in available_hwaccels:
                logger.warning(
                    f"Requested hardware accelerator {self.config.hwaccel} not available. "
                    "Falling back to software encoding."
                )
                self.config.hwaccel = "none"
                
        except subprocess.SubProcessError:
            logger.warning("Failed to check hardware acceleration. Using software encoding.")
            self.config.hwaccel = "none"

    @FFMPEG_LATENCY.time()
    def get_stream_options(self, width: Optional[int] = None, 
                         height: Optional[int] = None,
                         preset: Optional[str] = None,
                         hwaccel: Optional[str] = None) -> Dict[str, str]:
        """Generate FFmpeg streaming options."""
        width = width or self.config.width
        height = height or self.config.height
        preset = preset or self.config.preset
        hwaccel = hwaccel or self.config.hwaccel

        before_options = [
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
            "-nostdin"
        ]

        if hwaccel != "none":
            before_options.extend(["-hwaccel", hwaccel])

        options = [
            "-vf", f"scale={width}:{height}",
            "-c:v", "libx264",
            "-preset", preset,
            "-b:v", self.config.video_bitrate,
            "-maxrate", self.config.video_bitrate,
            "-bufsize", str(int(self.config.video_bitrate[:-1]) * 2) + "k",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", self.config.audio_bitrate,
            "-ar", "48000",
            "-ac", "2",
            "-f", "opus",
            "-thread_queue_size", str(self.config.thread_queue_size),
            "-threads", str(self.config.threads)
        ]

        return {
            "before_options": " ".join(before_options),
            "options": " ".join(options)
        }

    @TRANSCODE_DURATION.time()
    def transcode_media(self, input_path: str, output_path: str, 
                       options: Optional[Dict[str, str]] = None) -> None:
        """Transcode media using FFmpeg with proper error handling."""
        options = options or self.get_stream_options()
        cmd = [
            self.ffmpeg_path,
            *options["before_options"].split(),
            "-i", input_path,
            *options["options"].split(),
            output_path
        ]

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            stdout, stderr = process.communicate()

            if process.returncode != 0:
                raise StreamingError(f"FFmpeg transcode failed: {stderr}")

            logger.info(f"Successfully transcoded {input_path} to {output_path}")
            
        except Exception as e:
            raise StreamingError(f"Transcode failed: {str(e)}")

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
            except Exception as e:
                logger.error(f"Error collecting process stats for {path}: {e}")
        return stats

    async def _monitor_resources(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                stats = await self._collect_process_stats()
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
            async with self._process_semaphore:
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
            preexec_fn=lambda: None,
            env=env
        )

    def _prepare_process_environment(self) -> Dict[str, str]:
        return {
            'FFREPORT': f'file=ffmpeg-{time.time()}.log:level=32',
            'CUDA_VISIBLE_DEVICES': '',
            'FFMPEG_THREADS': '2'
        }

    def _build_optimized_command(self, media_path: str, quality: str) -> list:
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
            STREAM_QUALITY.set(bitrate / 1000)
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
        self._process_monitor.cancel()
        self._quality_monitor.cancel()
        try:
            await self._process_monitor
            await self._quality_monitor
        except asyncio.CancelledError:
            pass

    async def _monitor_stream_quality(self):
        while not self._shutdown_event.is_set():
            try:
                for path, stats in self._stream_stats.items():
                    if stats['errors'] > 3:
                        await self._adjust_stream_quality(path)
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error monitoring stream quality: {e}")
            await asyncio.sleep(10)

class PIDController:
    def __init__(self, Kp: float, Ki: float, Kd: float, setpoint: float):
        self.Kp = Kp
        self.Ki = Ki
        self.Kd = Kd
        self.setpoint = setpoint
        self.last_error = 0
        self.integral = 0

    def update(self, process_value: float, dt: float) -> float:
        error = self.setpoint - process_value
        self.integral += error * dt
        derivative = (error - self.last_error) / dt
        output = self.Kp * error + self.Ki * self.integral + self.Kd * derivative
        self.last_error = error
        return output