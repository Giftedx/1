import asyncio
import logging
import signal
import sys
import time
import uvloop
from contextlib import asynccontextmanager
from typing import AsyncIterator, Set, Dict, Any, List, Callable, Awaitable, Type
from collections import defaultdict
from prometheus_client import start_http_server, Counter, Gauge, Histogram
from src.monitoring.alerts import monitor_services
from src.utils.logging_setup import setup_logging
from src.utils.config import Config
from contextlib import AsyncExitStack
from src.utils.config import settings
from src.monitoring.circuit_breaker import CircuitBreaker
from src.monitoring.health import HealthCheck
from tenacity import retry, stop_after_attempt, wait_exponential
from src.utils.errors import ServiceInitError
from src.core.container import Container, RedisService, DiscordService, PlexService

setup_logging()
logger = logging.getLogger(__name__)

class GracefulExit(SystemExit):
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

async def shutdown(signal: signal.Signals, loop: asyncio.AbstractEventLoop) -> None:
    logger.info(f"Received exit signal {signal.name}...")
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    
    for task in tasks:
        task.cancel()
    
    logger.info(f"Cancelling {len(tasks)} tasks")
    await asyncio.gather(*tasks, return_exceptions=True)
    
    loop.stop()
    raise GracefulExit(signal.name)
async def app_lifespan() -> AsyncIterator[None]:
    config = Config()
    monitor_task = asyncio.create_task(monitor_services(alert_service=config.alert_service))
    
    try:
        yield
    finally:
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            logger.info("Monitoring task cancelled")

class Application:
    def __init__(self):
        self.cleanup_tasks: Set[asyncio.Task[Any]] = set()
        self._shutdown_event = asyncio.Event()
        self._startup_complete = asyncio.Event()
        self._services: Dict[str, Any] = {}
        self._startup_errors = Counter('app_startup_errors_total', 'Startup error count')
        self._shutdown_errors = Counter('app_shutdown_errors_total', 'Shutdown error count')
        self._service_health = Gauge('service_health_status', ['service'])
        self._service_dependencies: Dict[str, Set[str]] = {}
        self._dependency_graph: Dict[str, Set[str]] = defaultdict(set)
        self._metrics = {
            'service_startup_time': Histogram('service_startup_seconds', 
                                            'Service startup duration', 
                                            ['service']),
            'service_shutdown_time': Histogram('service_shutdown_seconds', 
                                             'Service shutdown duration', 
                                             ['service'])
        }
        self._health_checks: Dict[str, Callable[[], Awaitable[bool]]] = {}
        self._readiness_checks: Dict[str, Callable[[], Awaitable[bool]]] = {}
        self._health_status = Gauge('app_health_status', 'Application health status')
        self._readiness_status = Gauge('app_readiness_status', 'Application readiness status')
        self._exit_stack = AsyncExitStack()
        self._shutdown_handlers: Dict[str, Callable[[], Awaitable[None]]] = {}
        self._error_counts = Counter('app_errors_total', ['type', 'service'])
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._readiness_probes: Dict[str, Callable[[], Awaitable[bool]]] = {}
        self._retry_config: Dict[str, Any] = {
            'stop': stop_after_attempt(3),
            'wait': wait_exponential(multiplier=1, min=4, max=10)
        }
        self._service_timeouts = {
            'redis': 5.0,
            'plex': 15.0
        }
        self._container = Container()
        self._error_handlers: Dict[Type[Exception], Callable[[Exception], Awaitable[None]]] = {}
        
    def register_error_handler(self, exc_type: Type[Exception], handler: Callable):
        self._error_handlers[exc_type] = handler

    async def handle_error(self, error: Exception):
        error_type = type(error)
        handler = self._error_handlers.get(error_type)
        if handler:
            await handler(error)
        else:
            logger.error(f"Unhandled error: {error}", exc_info=error)
            self._error_counts.labels(
                type=error_type.__name__,
                service='unknown'
            ).inc()

    def _resolve_dependencies(self) -> List[str]:
        """Resolve service startup order using topological sort."""
        visited = set()
        temp_mark = set()
        order = []

        def visit(service: str):
            if service in temp_mark:
                raise ValueError("Circular dependency detected")
            if service in visited:
                return
            temp_mark.add(service)
            for dep in self._dependency_graph[service]:
                visit(dep)
            temp_mark.remove(service)
            visited.add(service)
            order.append(service)

        for service in self._services:
            if service not in visited:
                visit(service)
        return order

    async def init_services(self) -> None:
        """Initialize services with dependency ordering."""
        try:
            # Build dependency graph
            services_order = self._resolve_dependencies()
            
            for service_name in services_order:
                await self._init_service(service_name)
                self._service_health.labels(service=service_name).set(1)
                self._startup_order.append(service_name)
                
        except Exception as e:
            self._startup_errors.inc()
    @retry(**self._retry_config)
    async def _init_service(self, name: str) -> None:
        try:
            service = await asyncio.wait_for(self._container.resolve(name), timeout=self._service_timeouts.get(name, 10.0))
            await service.start()
            self._service_health.labels(service=name).set(1)
        except Exception as e:
            raise ServiceInitError(
                code="SERVICE_INIT_FAILED",
                message=f"Failed to initialize {name}"
            )

    async def _service_cleanup(self, name: str, cleanup_func: Callable[[], Awaitable[None]]) -> None:
        """Wrapper for service cleanup with error handling."""
        try:
            await cleanup_func()
        except Exception as e:
            self._shutdown_errors.inc()
            logger.error(f"Error cleaning up {name}: {e}")

    async def _cleanup_service(self, name: str) -> None:
        """
        Cleanup a single service with metrics.

        This method is responsible for cleaning up a specific service by calling its
        cleanup method and recording the duration of the cleanup process. If an error
        occurs during the cleanup, it increments the shutdown error counter and logs
        the error.

        Args:
            name (str): The name of the service to be cleaned up.
        """
        try:
            import time
            start_time = time.monotonic()
            service = self._services[name]
            await service.cleanup()
            duration = time.monotonic() - start_time
            self._metrics['service_shutdown_time'].labels(service=name).observe(duration)
        except Exception as e:
            self._shutdown_errors.inc()
            logger.error(f"Failed to cleanup {name}: {e}")

    async def register_health_check(self, name: str, check: Callable[[], Awaitable[bool]]) -> None:
        self._health_checks[name] = check

    async def register_readiness_check(self, name: str, check: Callable[[], Awaitable[bool]]) -> None:
        self._readiness_checks[name] = check

    async def _run_health_checks(self) -> bool:
        results = {}
        for name, check in self._health_checks.items():
            try:
                results[name] = await asyncio.wait_for(check(), timeout=5.0)
            except Exception as e:
                logger.error(f"Health check failed for {name}: {e}")
                results[name] = False
                self._error_counts.labels(type='health_check', service=name).inc()
        return all(isinstance(r, bool) and r for r in results.values())

    async def init_circuit_breakers(self) -> None:
        """Initialize circuit breakers for critical services."""
        self._circuit_breakers.update({
            'redis': CircuitBreaker(
                failure_threshold=5,
                recovery_timeout=30,
                name='redis'
            ),
            'discord': CircuitBreaker(
                failure_threshold=3,
                recovery_timeout=60,
                name='discord'
            )
        })

    async def register_readiness_probe(self, name: str, probe: Callable[[], Awaitable[bool]]) -> None:
        """Register a readiness probe for a service."""
        self._readiness_probes[name] = probe

    async def startup(self) -> None:
        """
        Initialize and start the application services.

        This method starts the metrics server, registers core services, initializes
        circuit breakers, and starts the core services in the correct order. If any
        error occurs during startup, it handles the error and raises an exception.

        Raises:
            Exception: If an error occurs during the startup process.
        """
        try:
            # Start metrics server
            start_http_server(settings.METRICS_PORT)
            
            # Register core services
            self._container.register("redis", RedisService)
            self._container.register("discord", DiscordService, ["redis"])
            self._container.register("plex", PlexService, ["redis"])
            
            # Initialize circuit breakers
            await self.init_circuit_breakers()
            
            # Initialize core services
            for service in self._startup_order:
                await self._init_service(service)
            
            self._startup_complete.set()
        except Exception as e:
            await self.handle_error(e)
            raise

    async def shutdown(self) -> None:
        """Enhanced shutdown with grace period."""
        if not self._shutdown_event.is_set():
            self._shutdown_event.set()
            try:
                await asyncio.gather(
                    *[self._cleanup_service(name) for name in reversed(self._startup_order)],
                    return_exceptions=True
                )
            except Exception as e:
                logger.error(f"Shutdown failed: {e}")
                self._shutdown_errors.inc()

    async def register_shutdown_handler(self, name: str, handler: Callable[[], Awaitable[None]]) -> None:
        """Register handlers for graceful shutdown."""
        self._shutdown_handlers[name] = handler

    async def cleanup(self) -> None:
        """Enhanced cleanup with proper error handling and timeouts."""
        async def _cleanup_with_timeout(name: str, handler: Callable[[], Awaitable[None]]) -> None:
            try:
                await asyncio.wait_for(handler(), timeout=10.0)
            except Exception as e:
                logger.error(f"Cleanup failed for {name}: {e}")
                self._error_counts.labels(type='cleanup', service=name).inc()

        await asyncio.gather(
            *[_cleanup_with_timeout(name, handler) for name, handler in self._shutdown_handlers.items()],
            return_exceptions=True
        )
        await self._exit_stack.aclose()

async def main() -> None:
    app = Application()
    
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            sig,
            lambda: asyncio.create_task(shutdown(sig, loop))
        )
    try:
        await app.startup()
        await app._shutdown_event.wait()
    except Exception as e:
        logger.error(f"Application error: {e}")
        sys.exit(1)
    finally:
        await app.cleanup()

if __name__ == "__main__":
    uvloop.install()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application shutdown by user")
