# Builder stage
FROM python:3.11-slim-bullseye as builder

# Add build optimizations
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_VERSION=1.5.1 \
    PYTHONOPTIMIZE=2 \
    PYTHONFAULTHANDLER=1 \
    PYTHONASYNCIODEBUG=0 \
    PYTHONDEVMODE=0

WORKDIR /install

COPY requirements.txt .

# Enhanced build with security checks
RUN set -ex \
    && pip install --no-cache-dir -U pip setuptools wheel \
    && pip install --prefix=/install --no-cache-dir -r requirements.txt \
    && pip install --prefix=/install safety bandit \
    && safety check \
    && find /install -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# Final stage
FROM python:3.11-slim-bullseye

# Add security optimizations
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        libsm6 \
        libxext6 \
        libgl1-mesa-glx \
        curl \
        tini \
        dumb-init \
        ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && adduser --system --group --no-create-home appuser \
    && mkdir -p /app /app/data \
    && chown -R appuser:appuser /app \
    && chmod -R 755 /app

WORKDIR /app
USER appuser

COPY --chown=appuser:appuser . .
COPY --from=builder /install /usr/local

# Final stage optimizations
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/usr/local/bin:$PATH" \
    PYTHONPATH="/app:$PYTHONPATH" \
    PYTHONHASHSEED=random \
    MALLOC_ARENA_MAX=2 \
    PYTHONMALLOC=malloc \
    MALLOC_TRIM_THRESHOLD_=65536 \
    GOMAXPROCS=2 \
    DD_TRACE_ENABLED=true \
    DD_PROFILING_ENABLED=true \
    DD_RUNTIME_METRICS_ENABLED=true

# Security labels
LABEL org.opencontainers.image.security.capabilities='{"drop": ["ALL"], "add": ["NET_BIND_SERVICE"]}' \
      org.opencontainers.image.source="https://github.com/yourusername/discord-media-bot" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="Your Organization" \
      org.opencontainers.image.version="1.0.0"

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=40s \
    CMD curl -f http://localhost:9090/health || exit 1

# Use tini and dumb-init for proper process management
ENTRYPOINT ["/usr/bin/dumb-init", "--", "/usr/bin/tini", "--"]
CMD ["python", "-m", "uvicorn", "src.api.health:app", \
     "--host", "0.0.0.0", \
     "--port", "9090", \
     "--workers", "2", \
     "--loop", "uvloop", \
     "--http", "httptools", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*", \
     "--timeout-keep-alive", "120", \
     "--backlog", "2048", \
     "--limit-concurrency", "1000", \
     "--limit-max-requests", "10000"]

EXPOSE 9090
