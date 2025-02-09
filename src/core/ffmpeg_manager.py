import asyncio
import logging
import signal
import os
import platform
import subprocess
import time
import psutil
from typing import Dict, Optional, List, AsyncGenerator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from src.utils.config import settings
from src.core.exceptions import StreamingError
from src.monitoring.metrics import FFMPEG_LATENCY, TRANSCODE_DURATION, FFMPEG_ERRORS, FFMPEG_PROCESSES, FFMPEG_CPU_USAGE, FFMPEG_MEMORY_USAGE

logger = logging.getLogger(__name__)

@dataclass
class FFmpegConfig:
    thread_queue_size: int = 512
    hwaccel: str = "auto"
    preset: str = "veryfast"
    width: int = 1280
    height: int = 720
    audio_bitrate: str = "192k"
    video_bitrate: str = "3000k"
    threads: int = 4  # Number of threads to use

class FFmpegManager:
    def __init__(self, ffmpeg_path: Optional[str] = None):  # Removed default, make explicit
        self._shutdown_event = asyncio.Event()
        self.config = FFmpegConfig(
            thread_queue_size=settings.FFMPEG_THREAD_QUEUE_SIZE,
            hwaccel=settings.FFMPEG_HWACCEL,
            preset=settings.FFMPEG_PRESET,
            width=settings.VIDEO_WIDTH,
            height=settings.VIDEO_HEIGHT
        )
        self._active_processes: Dict[str, asyncio.subprocess.Process] = {}
        self._verify_ffmpeg()
        self.resource_limits = {"max_cpu_percent": 80.0, "max_memory_mb": 1024, "max_processes": 5} # Added resource_limits to limit CPU usage
        self._process_monitor_task: Optional[asyncio.Task] = None
        self._adaptive_quality = True
        self._stream_stats = {}
        self._quality_monitor_task = None
        self.ffmpeg_path = ffmpeg_path or self._find_ffmpeg()
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
            "C:\\ffmpeg\\bin\\ffmpeg.exe" if platform.system() == "Windows" else None,  # Add default Windows path
        ]

        for path in filter(None, paths):  # Filter out None values (important for Windows path)
            try: # timeout
                subprocess.run([path, "-version"], capture_output=True, check=True, timeout=5)
                return path
            except (subprocess.SubProcessError, FileNotFoundError, TimeoutError): # Added timeout Error.
                continue

        raise StreamingError("FFmpeg not found. Please install FFmpeg or set the FFMPEG_PATH environment variable.")

    def _verify_ffmpeg(self) -> None:
        """Verify FFmpeg installation and capabilities."""
        try:
            result = subprocess.run(
                [self.ffmpeg_path, "-version"],
                capture_output=True,
                text=True,
                check=True,
            )
            logger.info(f"FFmpeg version: {result.stdout.splitlines()[0]}")
            
            # Check hardware acceleration support
            if self.config.hwaccel != "none":
                self._check_hwaccel()
                
        except subprocess.SubProcessError as e:
            raise StreamingError(f"FFmpeg verification failed: {e}")

    def _check_hwaccel(self) -> None:
        """Check hardware acceleration support."""
        try:
            result = subprocess.run(
                [self.ffmpeg_path, "-hwaccels"],
                capture_output=True,
                text=True,
                check=True
            ) # timeout
            available_hwaccels = result.stdout.strip().split('\n')[1:]
            logger.info(f"Available hardware accelerators: {', '.join(available_hwaccels)}")
            
            if self.config.hwaccel != "auto" and self.config.hwaccel not in available_hwaccels:
                logger.warning(
                    f"Requested hardware accelerator {self.config.hwaccel} not available. "
                    "Falling back to software encoding."
                )
                self.config.hwaccel = "none"
                
        except subprocess.SubProcessError as e:
            logger.warning("Failed to check hardware acceleration. Using software encoding.", exc_info=True)
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
            "-c:v", "libx264", # Use x264 codec
            "-preset", preset,
            "-b:v", self.config.video_bitrate,
            "-maxrate", self.config.video_bitrate,
            "-bufsize", str(int(self.config.video_bitrate[:-1]) * 2) + "k",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", self.config.audio_bitrate,
            "-ar", "48000",
            "-ac", "2", # Use stereo
            "-f", "flv",  # Use FLV for streaming to RTMP/RTMPS
            "-thread_queue_size", str(self.config.thread_queue_size), # apply config
            "-threads", str(self.config.threads), # apply config
        ]

        return {
            "before_options": " ".join(before_options),
            "options": " ".join(options)
        }

    @TRANSCODE_DURATION.time()
    def transcode_media(self, input_path: str, output_path: str,
                        options: Optional[Dict[str, str]] = None) -> None:
        """Transcode media using FFmpeg with proper error handling. Uses config, with optional overrides."""
        options = options or self.get_stream_options()
        cmd = [
            self.ffmpeg_path,
            *options["before_options"].split(),
            "-i", input_path,
            *options["options"].split(),
            output_path
        ] 
        cmd_str = " ".join(cmd)  # Log the full command
        logger.debug(f"Running FFmpeg command: {cmd_str}")

        try:
            process = subprocess.Popen( # Popen for error reporting
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

    @asynccontextmanager
    async def stream_session(self, media_path: str, quality: str, priority: int = 1): # Keep consistent signature, and add docstring
        """
            Manages starting the streaming session for ffmpeg.
            Manages resources and proper errors handling.
            params:
                media_path(str): Path to the media file.
                quality(str): Quality of the stream.
                priority(int): Priority of the stream.
            returns:
                process(asyncio.subprocess.Process): Async process object for the stream.
        """
        command = self._build_optimized_command(media_path, quality)  # consistent, build command
        process = await self._start_process_with_limits(command) # consistent naming, start process

        try:
            yield process  # the process
        except Exception as e:
            logger.error(f"Error in streaming session for {media_path}: {e}", exc_info=True)
            raise
        finally:
            await self._cleanup_process(process) # consistent with previous functions naming.

    async def _start_process_with_limits(self, command: list) -> asyncio.subprocess.Process:
        env = self._prepare_process_environment()
        try:
            return await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                limit=32768,  # Stream limit for performance
                preexec_fn=lambda: None,  # Simplified, platform-independent
                env=env, # apply env
            )
        except asyncio.subprocess.ProcessExitedQuickly as e:
            logger.error(f"Subprocess exited quickly {e.returncode} {e.stderr.decode()}", exc_info=True)
            FFMPEG_ERRORS.inc() # increment metric
            raise StreamingError("Subprocess ended")

        except OSError as e:  # More comprehensive error handling.
            logger.error(f"FFmpeg process creation failed: {e}")
            raise StreamingError(f"FFmpeg process creation failed: {e}")

    async def _collect_process_stats(self) -> Dict:
        stats = {'cpu_total': 0.0, 'memory_total': 0, 'process_count': len(self._active_processes)} # init stats
        for path, proc in list(self._active_processes.items()):
            try:
                process = psutil.Process(proc.pid)
                cpu = process.cpu_percent()
                memory = process.memory_info().rss / 1024 / 1024
                stats['cpu_total'] += cpu # add cpu
                stats['memory_total'] += memory # add memory
            except psutil.NoSuchProcess:
                self._active_processes.pop(path, None)
            except Exception as e:
                logger.error(f"Error collecting process stats for {path}: {e}")
        return stats

    def _prepare_process_environment(self) -> Dict[str, str]:
        # no LD_PRELOAD here, it's not safe
        
        env = {
            'FFREPORT': f'file=ffmpeg-{time.time()}.log:level=32',
            # Add more if required.
        }

        if platform.system() != 'Windows': # not working on Windows, CUDA_VISIBLE_DEVICES
            env['CUDA_VISIBLE_DEVICES'] = os.environ.get('CUDA_VISIBLE_DEVICES', '')

        if 'FFMPEG_THREADS' in os.environ: # added check to ensure thread is used if specified
            env['FFMPEG_THREADS'] = os.environ['FFMPEG_THREADS']

        return env

    def _build_optimized_command(self, media_path: str, quality: str) -> List[str]:
        bitrate = self._get_adaptive_bitrate(quality) # keep calling adaptive bitrate method
        command = [ # Use x264 codec, it's more compatible
            self.ffmpeg_path,            '-hide_banner',            '-loglevel', 'error',
            '-hwaccel', self.config.hwaccel,
            '-thread_queue_size', str(self.config.thread_queue_size),
            '-i', media_path,
            '-c:v', 'libx264',            '-preset', self.config.preset,
            '-b:v', bitrate,
            '-maxrate', f"{int(bitrate[:-1]) * 1.5}k",            '-bufsize', f"{int(bitrate[:-1]) * 2}k",
            '-profile:v', 'high', # optimize for web
            '-level', '4.1',
            '-crf', '23',            '-movflags', '+faststart',            '-g', '30',            '-keyint_min', '30',
            '-sc_threshold', '0',            '-c:a', 'aac',            '-b:a', '192k',            '-ar', '48000',
            '-ac', '2', # Use aac codec
            '-f', 'matroska',
            'pipe:1'
        ]
        return command

    def _get_adaptive_bitrate(self, quality: str) -> str:
        # Using settings for default and more granular bitrates, using a dict
        quality_presets = {
            'low': '1500k',            'medium': '3000k',            'high': '5000k',
            '720p': '4000k',
            '1080p': '8000k',
            '4k': '20000k'     # Explicit 4K setting
        }
        
        # Return preset if defined
        if quality in quality_presets:
            return quality_presets.get(quality, '3000k')

        return '3000k'
    
    async def stop_stream(self, media_path: str) -> None:
        """Gracefully stop a streaming process."""
        if media_path not in self._active_processes:
            logger.warning(f"No active FFmpeg process found for {media_path}.")
            return

        process = self._active_processes[media_path]
        
        if process.returncode is not None: # check if it's running
            logger.info(f"Stream process {media_path} already exited.")
            del self._active_processes[media_path]
            return
        
        logger.info(f"Stopping stream: {media_path}")
        
        # Send SIGINT to allow FFmpeg to shut down cleanly
        process.send_signal(signal.SIGINT)  # type: ignore (for signal types)
        
        try:
            await asyncio.wait_for(process.wait(), timeout=10) # monitor it's activity
            logger.info(f"Stopped stream {media_path} cleanly.")
        except asyncio.TimeoutError:
            logger.warning(f"Forcefully terminating FFmpeg process {media_path}.")
            process.kill()  # type: ignore (ignore method not known for non‑Windows.)
        
        except Exception as e:
            logger.exception(f"Error during stream stop operation : {e}")
        
        finally: # Corrected line
              self._active_processes.pop(media_path, None)
        FFMPEG_PROCESSES.set(len(self._active_processes))  # Corrected line

    async def _cleanup_process(self, process: Optional[asyncio.subprocess.Process]):
        # check we have a running process before cleanup, and kill it
        if process and process.returncode is None:
            with suppress(TimeoutError):
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=3.0) # reduce timeout, terminate after.
            if process.returncode is None:
                process.kill()  # If it can be killed
            
            logger.info(f"FFmpeg process {process.pid} stopped.")

    async def cleanup(self) -> None:
        """
        Clean all processes in the background.
        This is called on shutdown.
        """
        logger.info("cleaning all processes in the background.")
        
        if self._process_monitor_task:
            self._process_monitor_task.cancel()

            try:
                await self._process_monitor_task
            except asyncio.CancelledError:
                pass
        
        if self._quality_monitor_task:
            self._quality_monitor_task.cancel()
            try:
                await self._quality_monitor_task
            except asyncio.CancelledError:
                pass

        # Make sure all streams and monitor tasks are stopped/canceled, using a task group
        async with asyncio.TaskGroup() as tg:
            for path in list(self._active_processes.keys()):
                tg.create_task(self.stop_stream(path))
    
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

    async def _adjust_stream_quality(self, media_path: str) -> None:
        """Placeholder for stream quality adjustements.  This is a complex task."""
        pass # TODO: Implement adaptive quality

    async def set_adaptive_quality(self, value: bool) -> None:
        # Check config flag on init
        self._adaptive_quality = value
        logger.info(f"Adaptive quality set to: {self._adaptive_quality}")

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