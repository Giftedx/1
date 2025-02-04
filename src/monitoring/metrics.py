from prometheus_client import Counter, Gauge, Histogram
from typing import Optional
import functools
import time

# General metrics
REQUEST_COUNT = Counter('request_total', 'Total requests', ['endpoint'])
ERROR_COUNT = Counter('error_total', 'Total errors', ['type'])
LATENCY = Histogram('request_latency_seconds', 'Request latency', ['endpoint'])

# Resource metrics
MEMORY_USAGE = Gauge('memory_usage_bytes', 'Memory usage in bytes')
CPU_USAGE = Gauge('cpu_usage_percent', 'CPU usage percentage')
ACTIVE_CONNECTIONS = Gauge('active_connections', 'Number of active connections')

def track_latency(endpoint: str):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                REQUEST_COUNT.labels(endpoint=endpoint).inc()
                return result
            finally:
                duration = time.perf_counter() - start_time
                LATENCY.labels(endpoint=endpoint).observe(duration)
        return wrapper
    return decorator
