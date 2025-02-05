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
    && find /install -type d -name "__pycache__" -exec rm -rf {} + || true

# Final stage: added security optimizations and production healthcheck.
FROM python:3.11-slim-bullseye

# Add security optimizations
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libsm6 libxext6 curl tini dumb-init ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    adduser --system --group --no-create-home appuser && \
    mkdir -p /app && chown -R appuser:appuser /app && chmod -R 755 /app

WORKDIR /app
USER appuser

COPY --chown=appuser:appuser . .
COPY --from=builder /install /usr/local

# Enhanced runtime environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MALLOC_ARENA_MAX=2 \
    PYTHONMALLOC=malloc \
    GOMAXPROCS=2

# Setup process manager and healthcheck using dumb-init and tini.
ENTRYPOINT ["/usr/bin/tini", "--", "dumb-init"]

# Add healthcheck and start command.
HEALTHCHECK --interval=30s --timeout=10s CMD curl -f http://localhost:9090/health || exit 1
CMD ["python", "-m", "src.main"]

EXPOSE 9090
EXPOSE 8000
