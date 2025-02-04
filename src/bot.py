import asyncio
import logging
import discord
from discord.ext import commands
from src.utils.config import Config
from src.core.queue_manager import QueueManager
from src.core.ffmpeg_manager import FFmpegManager
from src.plex_server import PlexServer
from src.utils.rate_limiter import RateLimiter
from src.cogs.media_commands import MediaCommands
from src.dependencies import provide_redis_manager, provide_plex_server, provide_active_streams
import signal
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional, Set, Dict, Any
from src.core.health_check import HealthCheck
from src.utils.performance import measure_latency, CircuitBreaker
from src.core.di_container import Container
from src.core.service_manager import ServiceManager
from src.monitoring.heartbeat import HeartbeatMonitor
from prometheus_client import Counter, Histogram, Gauge

logger = logging.getLogger(__name__)

class MediaStreamingBot(commands.Bot):
    """
    Custom Discord bot for media streaming.
    """
    def __init__(self, config: Config):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            command_prefix="!",
            intents=intents,
            heartbeat_timeout=60.0,
            activity=discord.Activity(type=discord.ActivityType.watching, name="media streams")
        )
        self.config = config
        self.redis_manager = None
        self.queue_manager = None
        self.ffmpeg_manager = None
        self.plex_server = None
        self.rate_limiter = RateLimiter(
            config.RATE_LIMIT_REQUESTS,
            config.RATE_LIMIT_PERIOD
        )
        self.active_streams = None
        self._shutdown_event = asyncio.Event()
        self._cleanup_tasks: Set[asyncio.Task] = set()
        self.health_check = HealthCheck()
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=config.CIRCUIT_BREAKER_THRESHOLD,
            reset_timeout=config.CIRCUIT_BREAKER_TIMEOUT
        )
        self.container: Optional[Container] = None
        self.service_manager = ServiceManager()
        self.heartbeat = HeartbeatMonitor()
        self._command_latency = Histogram(
            'command_latency_seconds',
            'Command execution latency',
            ['command']
        )
        self._errors = Counter(
            'bot_errors_total',
            'Number of bot errors',
            ['type']
        )
        self._metrics = {
            'command_errors': Counter('bot_command_errors_total', 
                                    'Command error count', ['command']),
            'command_latency': Histogram('bot_command_latency_seconds',
                                       'Command execution time', ['command']),
            'active_commands': Gauge('bot_active_commands',
                                   'Number of active commands')
        }
        self._command_contexts: Dict[str, Any] = {}

    @asynccontextmanager
    async def graceful_shutdown(self) -> AsyncIterator[None]:
        try:
            yield
        finally:
            self._shutdown_event.set()
            cleanup_timeout = self.config.GRACEFUL_SHUTDOWN_TIMEOUT
            try:
                await asyncio.wait_for(self._cleanup(), timeout=cleanup_timeout)
            except asyncio.TimeoutError:
                logger.error(f"Cleanup timed out after {cleanup_timeout}s")

    async def _cleanup(self) -> None:
        tasks = [
            self.service_manager.cleanup(),
            self.heartbeat.shutdown(),
            self._cancel_cleanup_tasks(),
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    def _register_cleanup_task(self, task: asyncio.Task) -> None:
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_tasks.discard)

    async def _cancel_cleanup_tasks(self) -> None:
        for task in self._cleanup_tasks:
            task.cancel()
        if self._cleanup_tasks:
            await asyncio.gather(*self._cleanup_tasks, return_exceptions=True)

    async def setup_hook(self) -> None:
        try:
            # Initialize dependency container
            self.container = Container()
            self.container.config.override(self.config)
            self.container.wire(modules=[__name__, "src.cogs.media_commands"])

            # Register services
            await self.service_manager.register("redis", self.container.redis_manager())
            await self.service_manager.register("ffmpeg", self.container.ffmpeg_manager(), {"redis"})
            await self.service_manager.register("queue", self.container.queue_manager(), {"redis"})
            await self.service_manager.register("plex", self.plex_server)

            # Register heartbeats
            self.heartbeat.register("redis", self._check_redis_health)
            self.heartbeat.register("ffmpeg", self._check_ffmpeg_health)
            self.heartbeat.register("plex", self._check_plex_health)

            # Start services
            await self.service_manager.start_services()
            await self.heartbeat.start()

            config = self.config
            self.plex_server = await provide_plex_server(config)
            self.active_streams = provide_active_streams()
            self.active_streams.increment()
            await self.add_cog(MediaCommands(self))
            logger.info("Bot setup complete.")
            
            # Register signal handlers
            for sig in (signal.SIGTERM, signal.SIGINT):
                self.loop.add_signal_handler(sig, self._handle_signal)
                
            # Start monitoring tasks
            monitor_task = asyncio.create_task(self._monitor())
            self._register_cleanup_task(monitor_task)
            
            # Register health checks
            self.health_check.register("redis", self._check_redis_health)
            self.health_check.register("ffmpeg", self._check_ffmpeg_health)
            self.health_check.register("plex", self._check_plex_health)
            
            # Start health monitoring
            health_task = asyncio.create_task(self._health_monitor())
            self._register_cleanup_task(health_task)
            
        except Exception as e:
            logger.error(f"Failed to initialize bot: {e}", exc_info=True)
            raise

    def _handle_signal(self) -> None:
        self._shutdown_event.set()
        logger.info("Shutdown signal received")

    async def _monitor(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                await self._check_health()
            except Exception as e:
                logger.error(f"Health check failed: {e}")
            await asyncio.sleep(self.config.HEALTH_CHECK_INTERVAL)

    @measure_latency("health_check")
    async def _check_health(self) -> None:
        await self.health_check.run_checks()

    async def _check_redis_health(self) -> bool:
        try:
            await self.redis_manager.redis.ping()
            return True
        except Exception:
            return False

    async def _check_ffmpeg_health(self) -> bool:
        return len(self.ffmpeg_manager.active_processes) < self.config.MAX_CONCURRENT_STREAMS

    async def _check_plex_health(self) -> bool:
        try:
            await self.plex_server.ping()
            return True
        except Exception:
            return False

    async def _health_monitor(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                await self._check_health()
            except Exception as e:
                logger.error(f"Health check failed: {e}")
            await asyncio.sleep(self.config.HEALTH_CHECK_INTERVAL)

    async def close(self) -> None:
        await self.redis_manager.close()
        self.active_streams.decrement()
        await super().close()
        logger.info("Bot shutdown complete.")

    async def on_ready(self) -> None:
        logger.info(f"Logged in as {self.user}")

    async def on_message(self, message: discord.Message) -> None:
        if await self.rate_limiter.is_rate_limited(str(message.author.id)):
            await message.channel.send("You are being rate limited. Please try again later.")
            return
        await self.process_commands(message)

    async def on_error(self, event_method: str, *args, **kwargs) -> None:
        logger.error(f"Error in {event_method}", exc_info=True)

    async def on_command_error(self, ctx: commands.Context, error: Exception) -> None:
        error_type = type(error).__name__
        self._errors.labels(type=error_type).inc()
        logger.error(f"Command error: {error}", exc_info=True)
        await super().on_command_error(ctx, error)

    async def on_command(self, ctx: commands.Context) -> None:
        start_time = time.monotonic()
        try:
            await super().on_command(ctx)
        finally:
            duration = time.monotonic() - start_time
            self._command_latency.labels(ctx.command.name).observe(duration)

    async def process_commands(self, message: discord.Message) -> None:
        """Enhanced command processing with metrics."""
        if message.author.bot:
            return

        ctx = await self.get_context(message)
        if not ctx.command:
            return

        self._metrics['active_commands'].inc()
        try:
            async with self._track_command_metrics(ctx):
                await super().process_commands(message)
        finally:
            self._metrics['active_commands'].dec()

    @asynccontextmanager
    async def _track_command_metrics(self, ctx: commands.Context):
        """Track command execution metrics."""
        start_time = time.monotonic()
        command_name = ctx.command.name
        try:
            yield
        except Exception as e:
            self._metrics['command_errors'].labels(command=command_name).inc()
            raise
        finally:
            duration = time.monotonic() - start_time
            self._metrics['command_latency'].labels(command=command_name).observe(duration)
