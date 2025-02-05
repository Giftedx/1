import asyncio
import logging
import async_timeout
import time
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

from statistics import mean, stdev, median, quantiles

@dataclass
class AdaptiveConfig:
    min_timeout: float = 0.1
    max_timeout: float = 10.0
    window_size: int = 100
    success_threshold: float = 0.9

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failure_count = 0
        self._last_failure_time = 0
        self._state = CircuitState.CLOSED
        self._lock = asyncio.Lock()
        CB_STATE.labels(name='circuit_breaker').set(self._state.value)

    async def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        async with self._lock:
            if self._state == CircuitState.OPEN:
                if time.time() - self._last_failure_time > self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    CB_STATE.labels(name='circuit_breaker').set(self._state.value)
                else:
                    raise CircuitBreakerOpenError()

            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                if self._state == CircuitState.HALF_OPEN:
                    self._state = CircuitState.CLOSED
                    CB_STATE.labels(name='circuit_breaker').set(self._state.value)
                self._failure_count = 0
                CB_LATENCY.labels(name='circuit_breaker').observe(time.time() - start_time)
                return result
            except Exception as e:
                self._failure_count += 1
                CB_FAILURES.labels(name='circuit_breaker').inc()
                if self._failure_count >= self.failure_threshold:
                    self._state = CircuitState.OPEN
                    self._last_failure_time = time.time()
                    CB_STATE.labels(name='circuit_breaker').set(self._state.value)
                raise

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


    for _ in range(cb.config.failure_threshold):
        with pytest.raises(ValueError):
            await cb.call(failing_func)
            
    assert cb.state == CircuitState.OPEN
