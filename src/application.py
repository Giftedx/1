from prometheus_client import Counter, Gauge, Histogram, start_http_server
from contextlib import asynccontextmanager
from typing import Dict, Any, List

class Application:
    """Main application class managing services and lifecycle."""
    
    def __init__(self) -> None:
        self._startup_complete = asyncio.Event()
        self._shutdown_event = asyncio.Event()
        self._setup_metrics()
        self._setup_container()
        
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

    @asynccontextmanager
    async def _init_service(self, name: str) -> None:
        """Initialize a service with proper resource management."""
        try:
            async with self._resource_manager.resource_context(name):
                with self._resource_metrics.labels(type=name, operation='init').time():
                    await self._services[name].start()
                    yield
        except Exception as e:
            await self._handle_service_error(name, e)
            raise

    # ...existing code...
