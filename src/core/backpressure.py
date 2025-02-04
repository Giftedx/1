import asyncio
from typing import Callable, TypeVar, Any
from dataclasses import dataclass, field
from prometheus_client import Counter, Gauge, Histogram, Summary
import time

T = TypeVar('T')

REJECTED_REQUESTS = Counter('rejected_requests_total', 'Number of rejected requests due to backpressure')
QUEUE_PRESSURE = Gauge('queue_pressure', 'Current queue pressure level')

@dataclass
class BackpressureConfig:
    max_concurrent: int = 100
    max_queue_size: int = 1000
    queue_high_water: float = 0.8
    queue_low_water: float = 0.2

@dataclass
class BackpressureStats:
    total_requests: int = 0
    rejected_requests: int = 0
    current_queue_size: int = 0
    avg_latency: float = 0.0
    peak_queue_size: int = field(default=0)

class Backpressure:
    def __init__(self, config: BackpressureConfig):
        self.config = config
        self._semaphore = asyncio.Semaphore(config.max_concurrent)
        self._queue_size = 0
        self._latency = Histogram('request_latency_seconds',
                                'Request latency in seconds',
                                ['operation'])
        self._adaptive_limit = config.max_concurrent
        self._stats = BackpressureStats()
        self._metrics = {
            'queue_wait_time': Summary('request_queue_wait_seconds', 
                                     'Time spent waiting in queue'),
            'queue_peak_size': Gauge('queue_peak_size', 
                                   'Peak queue size reached')
        }

    async def execute(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        if self._queue_size >= self._adaptive_limit:
            REJECTED_REQUESTS.inc()
            raise asyncio.QueueFull("System overloaded")

        self._queue_size += 1
        QUEUE_PRESSURE.set(self._queue_size / self.config.max_queue_size)

        start_time = time.time()
        queue_start = time.monotonic()
        try:
            async with self._semaphore:
                result = await func(*args, **kwargs)
                latency = time.time() - start_time
                self._latency.labels(func.__name__).observe(latency)
                
                # Adjust limits based on latency
                if latency > 1.0:  # High latency threshold
                    self._adaptive_limit = max(
                        self._adaptive_limit * 0.8,
                        self.config.max_concurrent * 0.5
                    )
                return result
        finally:
            wait_time = time.monotonic() - queue_start
            self._metrics['queue_wait_time'].observe(wait_time)
            self._queue_size -= 1
            QUEUE_PRESSURE.set(self._queue_size / self.config.max_queue_size)
