import logging
import asyncio
from fastapi import FastAPI, status, Response, APIRouter, HTTPException
from opentelemetry import trace
from prometheus_client import Counter, Histogram, Gauge
from src.core.redis_manager import RedisManager
from src.core.plex_manager import PlexManager
from src.core.circuit_breaker import CircuitBreaker
from asyncio import TimeoutError
from datetime import datetime
import aiocache

logger = logging.getLogger(__name__)

app = FastAPI(title="Media Application Health Check", version="1.0.0")
router = APIRouter()

# Instantiate circuit breakers for Redis and Plex health checks.
redis_cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30)
plex_cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30)

# Add metrics
health_check_duration = Histogram('health_check_duration_seconds', 'Duration of health check', ['service'])
health_check_failures = Counter('health_check_failures_total', 'Total health check failures', ['service'])
service_up = Gauge('service_up', 'Service operational status', ['service'])
circuit_breaker_state = Gauge('circuit_breaker_state', 'Circuit breaker state', ['service'])

async def check_redis() -> bool:
    """
    Placeholder for Redis health check.
    """
    try:
        redis_manager = RedisManager()
        await redis_manager.ping()
        return True
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        return False

async def check_plex() -> bool:
    """
    Placeholder for Plex health check.
    """
    try:
        plex_server = PlexManager()
        plex_server.ping()
        return True
    except Exception as e:
        logger.error(f"Plex health check failed: {e}")
        return False

@aiocache.cached(ttl=5)  # Cache health results for 5 seconds
@router.get("/health", status_code=status.HTTP_200_OK)
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
                    redis_ok = await redis_cb.call(check_redis)
            except TimeoutError:
                logger.error("Redis health check timed out")
            except Exception as e:
                span.set_attribute("error", str(e))


            try:
                with tracer.start_span("plex_check"):
                    plex_ok = await plex_cb.call(check_plex)
            except TimeoutError:
                logger.error("Plex health check timed out")
            except Exception as e:
                span.set_attribute("error", str(e))

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

async def check_transcoder() -> bool:
    """
    This is a placeholder. Replace with your actual transcoder health check logic.
    """
    # Example: Try to connect to the transcoder service
    try:
        # Replace with your actual connection logic
        await asyncio.sleep(1)  # Simulate a connection attempt
        return True
    except Exception:
        return False

app.include_router(router)

<!DOCTYPE html>
<html>
<head>
    <title>Error</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
</head>
<body>
    <div class="container">
        <h1>Error</h1>
        <p>An error occurred: {{ error }}</p>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>