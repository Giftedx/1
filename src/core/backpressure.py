import asyncio
from typing import Callable, TypeVar, Any
from dataclasses import dataclass, field
from prometheus_client import Counter, Gauge, Histogram, Summary
import time
from collections import deque
from contextlib import asynccontextmanager

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
        self._load_calculator = LoadCalculator(window_size=60)
        self._adaptive_controller = AdaptiveController(
            min_limit=config.max_concurrent // 2,
            max_limit=config.max_concurrent
        )
        self._load_tracker = LoadTracker(window_size=60)
        self._rate_limiter = TokenBucketRateLimiter(
            rate=1000,
            burst=config.max_concurrent
        )
        self._load_predictor = LoadPredictor(
            history_size=60,
            prediction_window=5
        )
        self._rejection_strategy = GradualRejectionStrategy(
            min_threshold=0.7,
            max_threshold=0.9
        )

    async def execute(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        predicted_load = self._load_predictor.predict_load()
        if self._should_reject_request(predicted_load):
            raise BackpressureExceeded("Predicted overload")

        async with self._managed_execution():
            return await self._execute_with_monitoring(func, *args, **kwargs)

        if not await self._rate_limiter.acquire():
            raise BackpressureExceeded("Rate limit exceeded")
            
        load = self._load_tracker.current_load()
        if load > self.config.queue_high_water:
            self._adaptive_limit = max(
                self._adaptive_limit * 0.8,
                self.config.max_concurrent * 0.5
            )
        
        current_load = self._load_calculator.get_current_load()
        if current_load > self._adaptive_controller.threshold:
            self._adaptive_controller.decrease_limit()
            REJECTED_REQUESTS.inc()
            raise BackpressureExceeded("System overloaded")

        async with self._acquire_execution_slot():
            try:
                start_time = time.monotonic()
                result = await func(*args, **kwargs)
                execution_time = time.monotonic() - start_time
                
                self._load_calculator.record_execution(execution_time)
                self._adaptive_controller.update(execution_time)
                
                return result
            finally:
                self._release_execution_slot()

    @asynccontextmanager
    async def _acquire_execution_slot(self):
        if not await self._semaphore.acquire():
            raise BackpressureExceeded("No execution slots available")
        try:
            yield
        finally:
            self._semaphore.release()

    @asynccontextmanager
    async def _managed_execution(self):
        start = time.monotonic()
        try:
            yield
        finally:
            duration = time.monotonic() - start
            self._load_tracker.add_sample(duration)

class LoadTracker:
    def __init__(self, window_size: int):
        self._window = deque(maxlen=window_size)
        self._total_load = 0.0
        
    def add_sample(self, load: float) -> None:
        if len(self._window) == self._window.maxlen:
            self._total_load -= self._window[0]
        self._window.append(load)
        self._total_load += load
        
    def current_load(self) -> float:
        if not self._window:
            return 0.0
        return self._total_load / len(self._window)

class BackpressureManager:
    def __init__(self, max_concurrent: int = 5):
        self.semaphore = asyncio.Semaphore(max_concurrent)
    
    async def acquire(self):
        await self.semaphore.acquire()
    
    def release(self):
        self.semaphore.release()

@asynccontextmanager
async def execution_slot(semaphore: asyncio.Semaphore):
    await semaphore.acquire()
    try:
        yield
    finally:
        semaphore.release()
