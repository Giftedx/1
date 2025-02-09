from prometheus_client import Counter, Gauge, Histogram, start_http_server
from contextlib import asynccontextmanager
from typing import Dict, Any, List
import asyncio
import logging
import time

logger = logging.getLogger(__name__)

class Application:
    """Main application class managing services and lifecycle."""
    
    def __init__(self) -> None:
        self._startup_complete = asyncio.Event()
        self._shutdown_event = asyncio.Event()
        self._setup_metrics()
        # self._setup_container() # removed because it was causing an error

    def _setup_metrics(self) -> None:
        """Initialize Prometheus metrics."""
        self._startup_errors = Counter('app_startup_errors_total', 'Startup error count')
        self._shutdown_errors = Counter('app_shutdown_errors_total', 'Shutdown error count')
        self._service_health = Gauge('service_health', 'Service health status', ['service'])
        self._resource_metrics = Histogram(
            'resource_usage',
            'Resource usage metrics',
            ['type', 'operation'],
            buckets=[.001, .003, .01, .03, .1, .3, 1, 3, 10]
        )
        self._queue_size = Gauge('media_queue_size', 'Size of the media queue')
        self._rate_limit_errors = Counter('rate_limit_errors_total', 'Number of rate limit errors')
        self._response_times = Histogram(
            'response_times',
            'Response times of various operations',
            ['operation'],
            buckets=[.01, .025, .05, .075, .1, .25, .5, .75, 1.0, 2.5, 5.0, 7.5, 10.0]
        )

    @asynccontextmanager
    async def time_operation(self, operation_name: str):
        """Context manager to track the duration of an operation."""
        start_time = time.time()
        try:
            yield
        finally:
            duration = time.time() - start_time
            self._response_times.labels(operation=operation_name).observe(duration)

    # @asynccontextmanager # removed because it was causing an error
    # async def _init_service(self, name: str) -> None:
    #     """Initialize a service with proper resource management."""
    #     try:
    #         async with self._resource_manager.resource_context(name):
    #             with self._resource_metrics.labels(type=name, operation='init').time():
    #                 await self._services[name].start()
    #                 yield
    #     except Exception as e:
    #         await self._handle_service_error(name, e)
    #         raise

async def my_async_function():
    """Example async function using the time_operation context manager."""
    async with app.time_operation("my_async_function"):
        # Simulate some work
        await asyncio.sleep(1)
        return "Async function completed"
