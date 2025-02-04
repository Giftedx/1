import asyncio
import logging
from enum import Enum
from typing import Callable, TypeVar, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
from prometheus_client import Counter, Gauge, Histogram
from opentelemetry import trace
from src.core.circuit_breaker import CircuitBreaker
import aioredis
from fastapi import FastAPI, Response, status

T = TypeVar('T')
logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Metrics
CB_STATE = Gauge('circuit_breaker_state', 'Circuit breaker state', ['name'])
CB_FAILURES = Counter('circuit_breaker_failures_total', 'Circuit breaker failures', ['name'])
CB_LATENCY = Histogram('circuit_breaker_latency_seconds', 'Circuit breaker call latency', ['name'])

# System metrics
SYSTEM_INFO = Gauge('system_info', 'System information')
UPTIME = Counter('uptime_seconds', 'Service uptime in seconds')

# Application metrics  
REQUEST_COUNT = Counter('request_total', 'Total requests', ['endpoint'])
ERROR_COUNT = Counter('error_total', 'Total errors', ['type'])
LATENCY = Histogram('request_latency_seconds', 'Request latency', ['endpoint'])

# Media metrics
ACTIVE_STREAMS = Gauge('active_streams', 'Number of active media streams')
TRANSCODE_DURATION = Histogram('transcode_duration_seconds', 'Transcoding duration')

# Health check metrics
HEALTH_CHECK = Gauge('health_check', 'Health check status', ['component'])

class CircuitState(Enum):
    CLOSED = 0
    OPEN = 1
    HALF_OPEN = 2

@dataclass
class CircuitStats:
    total_calls: int = 0
    failed_calls: int = 0
    last_failure: Optional[datetime] = None 
    last_success: Optional[datetime] = None
    consecutive_failures: int = 0

@dataclass
class CircuitConfig:
    failure_threshold: int = 5
    recovery_timeout: int = 60
    half_open_max_calls: int = 3

class CircuitBreakerError(Exception):
    """Base exception for circuit breaker errors"""
    pass

class CircuitBreakerOpenError(CircuitBreakerError):
    """Raised when circuit is open"""
    pass

class CircuitBreakerHalfOpenError(CircuitBreakerError):
    """Raised when circuit exceeds half-open call limit"""
    pass

class CircuitBreaker:
    def __init__(self, name: str, config: Optional<CircuitConfig] = None):
        self.name = name
        self.config = config or CircuitConfig()
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self._half_open_calls = 0
        self._lock = asyncio.Lock()
        self._metrics = {
            'state': Gauge(f'circuit_breaker_{name}_state', 'Circuit breaker state'),
            'failures': Counter(f'circuit_breaker_{name}_failures', 'Number of failures'),
            'latency': Histogram(f'circuit_breaker_{name}_latency', 'Call latency')
        }
        self.stats = CircuitStats()
        self._state_change_time = datetime.now()
        
        # Initialize metrics
        CB_STATE.labels(name=self.name).set(self.state.value)

    async def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        async with self._lock:
            with tracer.start_span(f"circuit_breaker_{self.name}") as span:
                span.set_attribute("circuit_state", self.state.name)
                
                start_time = datetime.now()
                try:
                    await self._check_state_transition()
                    
                    if self.state == CircuitState.OPEN:
                        span.set_attribute("error", "circuit_open") 
                        raise CircuitBreakerOpenError(f"Circuit {self.name} is OPEN")
                    
                    if self.state == CircuitState.HALF_OPEN:
                        if self._half_open_calls >= self.config.half_open_max_calls:
                            span.set_attribute("error", "max_half_open_calls")
                            raise CircuitBreakerOpenError(f"Max half-open calls reached for {self.name}")
                        self._half_open_calls += 1

                    result = await func(*args, **kwargs)
                    await self._on_success()
                    return result

                except Exception as e:
                    await self._on_failure(e)
                    span.set_attribute("error", str(e))
                    raise

                finally:
                    duration = (datetime.now() - start_time).total_seconds()
                    CB_LATENCY.labels(name=self.name).observe(duration)

    async def _check_state_transition(self) -> None:
        now = datetime.now()
        if self.state == CircuitState.OPEN:
            if now - self._state_change_time > timedelta(seconds(self.config.recovery_timeout)):
                logger.info(f"Circuit {self.name} transitioning from OPEN to HALF_OPEN")
                self.state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                self._state_change_time = now
                CB_STATE.labels(name=self.name).set(self.state.value)

    async def _on_success(self) -> None:
        self.stats.total_calls += 1
        self.stats.consecutive_failures = 0
        self.stats.last_success = datetime.now()
        
        if self.state == CircuitState.HALF_OPEN:
            logger.info(f"Circuit {self.name} recovered, transitioning to CLOSED")
            self.state = CircuitState.CLOSED
            self._half_open_calls = 0
            self.stats.failed_calls = 0
            CB_STATE.labels(name=self.name).set(self.state.value)

    async def _on_failure(self, error: Exception) -> None:
        self.stats.total_calls += 1
        self.stats.failed_calls += 1
        self.stats.consecutive_failures += 1
        self.stats.last_failure = datetime.now()
        CB_FAILURES.labels(name=self.name).inc()

        if (self.state == CircuitState.CLOSED and 
            self.stats.consecutive_failures >= self.config.failure_threshold):
            logger.warning(f"Circuit {self.name} tripped, transitioning to OPEN")
            self.state = CircuitState.OPEN
            self._state_change_time = datetime.now()
            CB_STATE.labels(name=self.name).set(self.state.value)
        elif self.state == CircuitState.HALF_OPEN:
            logger.warning(f"Circuit {self.name} failed in HALF_OPEN, returning to OPEN")
            self.state = CircuitState.OPEN
            self._state_change_time = datetime.now()
            CB_STATE.labels(name=self.name).set(self.state.value)

    def get_stats(self) -> CircuitStats:
        return self.stats

    def reset(self) -> None:
        self.state = CircuitState.CLOSED
        self.stats = CircuitStats()
        self._half_open_calls = 0
        self._state_change_time = datetime.now()
        CB_STATE.labels(name=self.name).set(self.state.value)

class RedisManager:
    def __init__(self, url: str):
        self.url = url
        self.pool: Optional[aioredis.Redis] = None
        self.circuit_breaker = CircuitBreaker('redis')
        self._metrics = {
            'connections': Gauge('redis_connections', 'Active Redis connections'),
            'operations': Counter('redis_operations', 'Redis operations', ['type'])
        }

async def health_check_endpoint(response: Response):
    checks = {
        'redis': check_redis(),
        'plex': check_plex(),
        'transcoder': check_transcoder()
    }
    
    is_healthy = all(checks.values())
    response.status_code = status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    
    for component, status in checks.items():
        HEALTH_CHECK.labels(component=component).set(1 if status else 0)
        
    return {'status': 'healthy' if is_healthy else 'unhealthy', 'checks': checks}

import pytest
from datetime import datetime, timedelta
from src.core.circuit_breaker import CircuitBreaker, CircuitState, CircuitConfig
from src.core.exceptions import CircuitBreakerOpenError

@pytest.mark.asyncio
async def test_circuit_breaker_basic():
    cb = CircuitBreaker("test")
    
    # Test successful calls
    result = await cb.call(lambda: "success")
    assert result == "success"
    assert cb.state == CircuitState.CLOSED
    
    # Test failure threshold
    async def failing_func():
        raise ValueError("test error")
        
    for _ in range(cb.config.failure_threshold):
        with pytest.raises(ValueError):
            await cb.call(failing_func)
            
    assert cb.state == CircuitState.OPEN
