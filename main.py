import asyncio
import logging
import signal
import sys
import time
import uvloop
from contextlib import asynccontextmanager, suppress
from typing import AsyncIterator, Set, Dict, Any, List, Callable, Awaitable, Type, Optional
from collections import defaultdict
from prometheus_client import start_http_server, Counter, Gauge, Histogram, exponential_buckets
from src.monitoring.alerts import monitor_services
from src.utils.logging_setup import setup_logging
from src.utils.config import Config
from contextlib import AsyncExitStack
from src.utils.config import settings
from src.monitoring.circuit_breaker import CircuitBreaker
from src.monitoring.health import HealthCheck
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from src.utils.errors import ServiceInitError
from src.core.container import Container, RedisService, DiscordService, PlexService

setup_logging()
logger = logging.getLogger(__name__)

class GracefulExit(SystemExit):
    pass

async def shutdown(signal: signal.Signals, loop: asyncio.AbstractEventLoop) -> None:
    """
    Shuts down the application gracefully.

    This function cancels all pending tasks, logs the cancellation, and stops the event loop.

    Args:
        signal (signal.Signals): The signal that triggered the shutdown.
        loop (asyncio.AbstractEventLoop): The event loop to stop.
    """
    logger.info(f"Received exit signal {signal.name}...")
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    for task in tasks:
        task.cancel()

    logger.info(f"Cancelling {len(tasks)} tasks")
    await asyncio.gather(*tasks, return_exceptions=True)

    loop.stop()
    raise GracefulExit(signal.name)

async def app_lifespan() -> AsyncIterator[None]:
    """
    Manages the application lifespan, starting and cancelling monitoring tasks.

    This function starts a monitoring task to observe the health of services and cancels it upon exit.

    Yields:
        None: Yields control to the application.
    """
    config = Config()
    monitor_task = asyncio.create_task(monitor_services(alert_service=config.alert_service))

    try:
        yield
    finally:
        monitor_task.cancel()
        with suppress(asyncio.CancelledError):
            await monitor_task

class AdaptiveTimeoutManager:
    """
    Manages adaptive timeouts for service operations based on historical performance.

    This class adjusts timeouts dynamically based on the observed latencies of service operations,
    allowing the system to adapt to varying load and performance conditions.
    """
    def __init__(self, min_timeout: float, max_timeout: float, history_size: int = 10):
        """
        Initializes the AdaptiveTimeoutManager with minimum and maximum timeout values, and a history size.

        Args:
            min_timeout (float): The minimum allowed timeout value.
            max_timeout (float): The maximum allowed timeout value.
            history_size (int): The number of historical latency values to consider when adjusting the timeout.
        """
        self._min_timeout = min_timeout
        self._max_timeout = max_timeout
        self._history_size = history_size
        self._operation_history: Dict[str, List[float]] = defaultdict(list)

    def record_latency(self, operation_name: str, latency: float) -> None:
        """
        Records the latency of a service operation.

        Args:
            operation_name (str): The name of the operation.
            latency (float): The observed latency of the operation.
        """
        history = self._operation_history[operation_name]
        history.append(latency)
        if len(history) > self._history_size:
            history.pop(0)

    def get_timeout(self, operation_name: str) -> float:
        """
        Calculates and returns the adaptive timeout value for a service operation.

        The timeout is calculated based on the historical latencies of the operation, with safeguards
        to ensure it remains within the predefined minimum and maximum bounds.

        Args:
            operation_name (str): The name of the operation.

        Returns:
            float: The adaptive timeout value for the operation.
        """
        history = self._operation_history[operation_name]
        if not history:
            return self._min_timeout  # Default timeout if no history

        average_latency = sum(history) / len(history)
        # Adjust timeout based on average latency, with a safety margin
        timeout = min(max(average_latency * 2, self._min_timeout), self._max_timeout)
        return timeout

class ResourcePool:
    """
    Manages a pool of resources, limiting the number of active and idle resources.

    This class is designed to efficiently manage resources by maintaining a pool of reusable instances,
    reducing the overhead of creating and destroying resources frequently.
    """
    def __init__(self, max_size: int, max_idle: int, cleanup_interval: int = 60):
        """
        Initializes the ResourcePool with maximum sizes and a cleanup interval.

        Args:
            max_size (int): The maximum number of resources that can be active at any time.
            max_idle (int): The maximum number of idle resources to keep in the pool.
            cleanup_interval (int): The interval (in seconds) at which to run the cleanup task.
        """
        self._max_size = max_size
        self._max_idle = max_idle
        self._pool: asyncio.Queue[Any] = asyncio.Queue(maxsize=max_size)
        self._active_count = 0
        self._cleanup_interval = cleanup_interval
        self._cleanup_task: Optional[asyncio.Task[None]] = None

    async def start(self) -> None:
        """Starts the resource pool's cleanup task."""
        self._cleanup_task = asyncio.create_task(self._cleanup_idle_resources())

    async def stop(self) -> None:
        """Stops the resource pool's cleanup task and clears the pool."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._cleanup_task
        while not self._pool.empty():
            await self._pool.get()

    async def acquire(self) -> Any:
        """
        Acquires a resource from the pool, creating a new one if necessary.

        Returns:
            Any: A resource from the pool.

        Raises:
            Exception: If the maximum number of active resources has been reached.
        """
        if self._active_count >= self._max_size:
            raise Exception("Maximum number of active resources reached")

        if not self._pool.empty():
            resource = await self._pool.get()
            self._active_count += 1
            return resource
        else:
            self._active_count += 1
            return await self._create_resource()

    async def release(self, resource: Any) -> None:
        """
        Releases a resource back into the pool, or destroys it if the pool is full.

        Args:
            resource (Any): The resource to release.
        """
        if self._pool.qsize() < self._max_idle:
            await self._pool.put(resource)
        else:
            await self._destroy_resource(resource)
        self._active_count -= 1

    async def _create_resource(self) -> Any:
        """
        Abstract method to create a new resource. Must be implemented by subclasses.

        Raises:
            NotImplementedError: If the method is not implemented by a subclass.
        """
        raise NotImplementedError

    async def _destroy_resource(self, resource: Any) -> None:
        """
        Abstract method to destroy a resource. Must be implemented by subclasses.

        Args:
            resource (Any): The resource to destroy.

        Raises:
            NotImplementedError: If the method is not implemented by a subclass.
        """
        raise NotImplementedError

    async def _cleanup_idle_resources(self) -> None:
        """Periodically cleans up idle resources in the pool."""
        while True:
            await asyncio.sleep(self._cleanup_interval)
            while self._pool.qsize() > self._max_idle:
                resource = await self._pool.get()
                await self._destroy_resource(resource)

class ResourceManager:
    """
    Manages the lifecycle of services, including acquisition, cleanup, and error handling.

    This class provides a centralized mechanism for managing services, ensuring they are properly
    initialized, cleaned up, and that errors are handled gracefully.
    """
    def __init__(self, cleanup_batch_size: int = 10, max_concurrent_cleanups: int = 5):
        """
        Initializes the ResourceManager with batch sizes and concurrency limits for cleanup operations.

        Args:
            cleanup_batch_size (int): The number of resources to clean up in each batch.
            max_concurrent_cleanups (int): The maximum number of concurrent cleanup operations.
        """
        self._services: Dict[str, Any] = {}
        self._cleanup_batch_size = cleanup_batch_size
        self._max_concurrent_cleanups = max_concurrent_cleanups
        self._cleanup_semaphore = asyncio.Semaphore(max_concurrent_cleanups)
        self._resource_metrics = Histogram(
            'resource_usage',
            'Resource usage metrics',
            ['type', 'operation'],
            buckets=exponential_buckets(0.001, 2, 15)
        )
        self._cleanup_latency = Histogram(
            'cleanup_latency',
            'Resource cleanup latency',
            ['resource_type'],
            buckets=exponential_buckets(0.01, 2, 10)
        )

    async def acquire_service(self, name: str, timeout: float) -> Any:
        """
        Acquires a service, initializing it if necessary.

        Args:
            name (str): The name of the service to acquire.
            timeout (float): The timeout for the service initialization.

        Returns:
            Any: The initialized service.
        """
        if name not in self._services:
            self._services[name] = await self._initialize_service(name, timeout)
        return self._services[name]

    async def _initialize_service(self, name: str, timeout: float) -> Any:
        """
        Initializes a service, handling potential errors and timeouts.

        Args:
            name (str): The name of the service to initialize.
            timeout (float): The timeout for the service initialization.

        Returns:
            Any: The initialized service.

        Raises:
            ServiceInitError: If the service fails to initialize within the given timeout.
        """
        try:
            with asyncio.timeout(timeout):
                # Assuming Container().get_service returns an awaitable
                service = await Container().get_service(name)
                return service
        except asyncio.TimeoutError:
            logger.error(f"Service {name} initialization timed out")
            raise ServiceInitError(f"Service {name} initialization timed out")
        except Exception as e:
            logger.error(f"Failed to initialize service {name}: {e}")
            raise ServiceInitError(f"Failed to initialize service {name}: {e}")

    @asynccontextmanager
    async def cleanup_context(self, name: str):
        """
        Provides a context for cleaning up a service, ensuring proper error handling and metrics.

        Args:
            name (str): The name of the service to clean up.

        Yields:
            None: Yields control to the context.
        """
        try:
            yield
        except Exception as e:
            logger.error(f"Error during cleanup of {name}: {e}")
        finally:
            with self._cleanup_latency.labels(resource_type=name).time():
                await self._cleanup_service(name)

    async def _cleanup_service(self, name: str) -> None:
        """
        Cleans up a service, handling potential errors during the cleanup process.

        Args:
            name (str): The name of the service to clean up.
        """
        try:
            service = self._services.pop(name, None)
            if service and hasattr(service, 'cleanup') and callable(service.cleanup):
                async with self._cleanup_semaphore:
                    await service.cleanup()
        except Exception as e:
            logger.error(f"Failed to cleanup service {name}: {e}")

class PerformanceMetrics:
    """
    Collects and manages performance metrics for various operations.

    This class provides a convenient way to track the performance of different operations by
    recording their execution times and providing histograms for analysis.
    """
    def __init__(self, buckets: List[float] = None):
        """
        Initializes the PerformanceMetrics with a list of histogram buckets.

        Args:
            buckets (List[float]): A list of bucket boundaries for the histograms.
        """
        if buckets is None:
            buckets = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]  # Default buckets
        self._buckets = buckets
        self._operation_times: Dict[str, Histogram] = {}

    @contextmanager
    async def track_operation(self, operation_name: str):
        """
        Tracks the execution time of an operation using a context manager.

        Args:
            operation_name (str): The name of the operation to track.

        Yields:
            None: Yields control to the context.
        """
        start_time = time.time()
        try:
            yield
        finally:
            elapsed_time = time.time() - start_time
            if operation_name not in self._operation_times:
                self._operation_times[operation_name] = Histogram(
                    f'{operation_name}_duration_seconds',
                    f'Duration of {operation_name} operation',
                    buckets=self._buckets
                )
            self._operation_times[operation_name].observe(elapsed_time)

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
        # Add improved metric collectors
        self._resource_metrics = Histogram(
            'resource_usage',
            'Resource usage metrics',
            ['type', 'operation'],
            buckets=exponential_buckets(0.001, 2, 15)
        )
        self._cleanup_latency = Histogram(
            'cleanup_latency',
            'Resource cleanup latency',
            ['resource_type'],
            buckets=exponential_buckets(0.01, 2, 10)
        )
        self._adaptive_timeout_manager = AdaptiveTimeoutManager(
            min_timeout=0.1,
            max_timeout=30.0,
            history_size=10
        )
        self._resource_pool = ResourcePool(
            max_size=100,
            max_idle=10,
            cleanup_interval=60
        )
        self._resource_manager = ResourceManager(
            cleanup_batch_size=10,
            max_concurrent_cleanups=5
        )
        self._performance_metrics = PerformanceMetrics(
            buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]
        )
        
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
            with self._performance_metrics.track_operation(f"init_{name}"):
                service = await self._resource_manager.acquire_service(
                    name, 
                    timeout=self._adaptive_timeout_manager.get_timeout(name)
                )
                await service.start()
        except Exception as e:
            self._startup_errors.inc()
            await self._handle_service_error(name, e)
            raise

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
            async with self._resource_manager.cleanup_context(name):
                with self._resource_metrics.labels(type=name, operation='cleanup').time():
                    await self._services[name].cleanup()
        except Exception as e:
            await self._handle_cleanup_error(name, e)

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
