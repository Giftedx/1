import logging
import asyncio
from fastapi import FastAPI, status, Response
from opentelemetry import trace
from prometheus_client import Counter, Histogram, Gauge
from src.core.redis_manager import RedisManager
from src.plex_server import PlexServer
from src.core.circuit_breaker import CircuitBreaker
from asyncio import TimeoutError
from datetime import datetime
import aiocache

logger = logging.getLogger(__name__)

app = FastAPI(title="Media Application Health Check", version="1.0.0")

# Instantiate circuit breakers for Redis and Plex health checks.
redis_cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30)
plex_cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30)

# Add metrics
health_check_duration = Histogram('health_check_duration_seconds', 'Duration of health check', ['service'])
health_check_failures = Counter('health_check_failures_total', 'Total health check failures', ['service'])
service_up = Gauge('service_up', 'Service operational status', ['service'])
circuit_breaker_state = Gauge('circuit_breaker_state', 'Circuit breaker state', ['service'])

@aiocache.cached(ttl=5)  # Cache health results for 5 seconds
@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check(response: Response) -> dict:
    start = datetime.now()
    try:
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("health_check") as span:
            redis_ok = False
            plex_ok = False
            redis_latency = None
            plex_latency = None
            start_time = datetime.utcnow()
            redis_metrics = {}
            try:
                with tracer.start_span("redis_check"):
                    with health_check_duration.labels('redis').time():
                        redis_manager = await RedisManager.create()
                        redis_info = await redis_cb.call(redis_manager.info)
                        redis_ok = True
                        redis_metrics = {
                            "connected_clients": redis_info.get("connected_clients"),
                            "used_memory_rss": redis_info.get("used_memory_rss"),
                            "ops_per_sec": redis_info.get("instantaneous_ops_per_sec")
                        }
                        redis_latency = (datetime.utcnow() - start_time).total_seconds()
                        logger.debug(f"Redis health check passed. Latency: {redis_latency}s")
                    circuit_breaker_state.labels('redis').set(redis_cb.state.value)
                    service_up.labels('redis').set(1 if redis_ok else 0)
            except TimeoutError:
                logger.error("Redis health check timed out")
            except Exception as e:
                span.set_attribute("error", str(e))
                health_check_failures.labels('redis').inc()
                logger.error(f"Redis health check failed: {e}")

            try:
                with tracer.start_span("plex_check"):
                    with health_check_duration.labels('plex').time():
                        plex_server = PlexServer.get_instance()
                        await asyncio.wait_for(plex_cb.call(plex_server.ping), timeout=5.0)
                        plex_ok = True
                        plex_latency = (datetime.utcnow() - start_time).total_seconds()
                        logger.debug(f"Plex health check passed. Latency: {plex_latency}s")
                    circuit_breaker_state.labels('plex').set(plex_cb.state.value)
                    service_up.labels('plex').set(1 if plex_ok else 0)
            except TimeoutError:
                logger.error("Plex health check timed out")
            except Exception as e:
                span.set_attribute("error", str(e))
                health_check_failures.labels('plex').inc()
                logger.error(f"Plex health check failed: {e}")

            status_value = "healthy" if redis_ok and plex_ok else "degraded"

            # Set degraded status code
            if not (redis_ok and plex_ok):
                response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

            checks = {
                'redis': redis_ok,
                'plex': plex_ok,
                'transcoder': await check_transcoder()
            }
            is_healthy = all(checks.values())
    except Exception as e:
        logger.error(f"Health check failure: {e}")
        is_healthy = False
        checks = {"error": str(e)}
    duration = (datetime.now() - start).total_seconds()
    health_check_duration.labels(service="all").observe(duration)
    response.status_code = status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    for component, stat in checks.items():
        service_up.labels(service=component).set(1 if stat is True else 0)
    return {'status': 'healthy' if is_healthy else 'unhealthy', 'checks': checks}

async def check_transcoder():
    # Replace this stub with actual transcoder health check logic
    return True