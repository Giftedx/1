from prometheus_client import Counter, Gauge, Histogram, Summary
from typing import Dict, Any, Optional, ContextManager, List, Callable
from threading import Lock
import time
import contextlib
from dataclasses import dataclass, field
from contextlib import contextmanager, AsyncExitStack
from typing import AsyncGenerator, Optional

@dataclass
class MetricDefinition:
    name: str
    description: str
    type: str
    labels: Optional[List[str]] = None

@dataclass
class MetricConfig:
    name: str
    description: str
    type: str
    labels: List[str] = field(default_factory=list)
    buckets: Optional[List[float]] = None

class ActiveStreams:
    _current_value = 0

    @classmethod
    def get_current_value(cls) -> float:
        return cls._current_value

    @classmethod
    def set_current_value(cls, value: float) -> None:
        cls._current_value = value

    @classmethod
    def increment(cls, value: float = 1) -> None:
        cls._current_value += value

    @classmethod
    def decrement(cls, value: float = 1) -> None:
        cls._current_value -= value

class Metrics:
    """Enhanced thread-safe metrics collection."""
    def __init__(self):
        self._lock = Lock()
        self._metrics: Dict[str, Any] = {
            'active_streams': Gauge(
                'active_streams_total',
                'Number of active media streams'
            ),
            'stream_quality': Histogram(
                'stream_quality_seconds',
                'Stream quality metrics',
                ['quality']
            ),
            'errors': Counter(
                'errors_total',
                'Total number of errors',
                ['type', 'severity']
            )
        }

    def increment_active_streams(self) -> None:
        with self._lock:
            self._metrics['active_streams'].inc()

    def decrement_active_streams(self) -> None:
        with self._lock:
            self._metrics['active_streams'].dec()

    def record_error(self, error_type: str, severity: str = 'error') -> None:
        with self._lock:
            self._metrics['errors'].labels(
                type=error_type,
                severity=severity
            ).inc()

    def increment(self, metric: str, value: float = 1.0, labels: Dict[str, str] = None) -> None:
        with self._lock:
            if labels:
                self._metrics[metric].labels(**labels).inc(value)
            else:
                self._metrics[metric].inc(value)

    def set_value(self, metric: str, value: float, labels: Dict[str, str] = None) -> None:
        with self._lock:
            if labels:
                self._metrics[metric].labels(**labels).set(value)
            else:
                self._metrics[metric].set(value)

    def get_value(self, metric: str, labels: Dict[str, str] = None) -> float:
        with self._lock:
            if labels:
                return self._metrics[metric].labels(**labels)._value.get()
            return self._metrics[metric]._value.get()

    @contextlib.contextmanager
    def timer(self, operation: str, labels: Optional[Dict[str, str]] = None) -> ContextManager:
        start_time = time.monotonic()
        status = 'success'
        try:
            yield
        except Exception:
            status = 'error'
            raise
        finally:
            duration = time.monotonic() - start_time
            if labels:
                self._metrics['latencies'].labels(operation=operation, status=status, **labels).observe(duration)
            else:
                self._metrics['latencies'].labels(operation=operation, status=status).observe(duration)

    @contextlib.contextmanager
    def timing_context(self, operation: str, labels: Optional[Dict[str, str]] = None) -> None:
        """Enhanced timing context with error tracking and resource monitoring."""
        start_time = time.monotonic()
        status = 'success'
        try:
            yield
        except Exception as e:
            status = 'error'
            self.record_error(type(e).__name__, 'error')
            raise
        finally:
            duration = time.monotonic() - start_time
            self._metrics['latencies'].labels(
                operation=operation,
                status=status,
                **(labels or {})
            ).observe(duration)

    def track_resource(self, resource_type: str, value: float) -> None:
        """Track resource usage."""
        self._metrics['resource_usage'].labels(resource_type=resource_type).set(value)

    @contextmanager
    def batch_operation(self) -> AsyncGenerator[None, None]:
        """Context manager for batching metric operations."""
        with self._lock:
            try:
                yield
            finally:
                self._flush_metrics()

    def _flush_metrics(self) -> None:
        """Flush any buffered metrics."""
        pass  # Implement metric flushing if needed

    async def cleanup(self) -> None:
        """Cleanup metric resources."""
        await self._exit_stack.aclose()

# Global metrics instance
METRICS = Metrics()

# Expose ACTIVE_STREAMS as an instance of ActiveStreams.
ACTIVE_STREAMS = ActiveStreams()

# Media streaming metrics
MEDIA_ACTIVE_STREAMS = Gauge('media_active_streams', 'Number of active media streams')
STREAM_QUALITY = Gauge('media_stream_quality_kbps', 'Stream quality in kbps')
STREAM_ERRORS = Counter('media_stream_errors_total', 'Total number of stream errors')

# Plex metrics
PLEX_REQUESTS = Counter('plex_requests_total', 'Total number of Plex API requests')
PLEX_ERRORS = Counter('plex_errors_total', 'Total number of Plex API errors')

# FFmpeg metrics
FFMPEG_ERRORS = Counter('ffmpeg_errors_total', 'Total number of FFmpeg errors')
TRANSCODE_TIME = Histogram(
    'transcode_duration_seconds',
    'Time spent transcoding media',
    buckets=[1, 5, 10, 30, 60, 120, 300]
)

# Discord metrics
DISCORD_COMMANDS = Counter('discord_commands_total', 'Total Discord commands received')
VOICE_CONNECTIONS = Gauge('discord_voice_connections', 'Active voice channel connections')
