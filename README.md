# Media Application

This application handles media streaming and processing via FFmpeg, Redis, and Plex. It features:

- **FFmpeg process management** with asynchronous error handling.
- **Enhanced circuit breaker** implementation for resilient operation.
- **Redis‑backed distributed rate limiting**.
- **Queue management** for media tasks.
- A **Discord bot** that listens for commands and adds media to the processing queue.
- A separate **self‑bot** for streaming via Plex.
- A **health check endpoint** for container orchestration.
- **Monitoring alerts and Prometheus metrics**.
- A **CI/CD pipeline** via GitHub Actions.
- Secure secret management with Vault (or environment variables).

## Setup Instructions

1. **Clone the repository:**

   ```bash
   git clone https://your-repo-url/media-bot.git
   cd media-bot
   ```

2. **Configure environment variables:**

   Copy the example file and edit as required:

   ```bash
   cp .env.example .env
   ```

3. **Install dependencies:**

   ```bash
   pip install --no-cache-dir -r requirements.txt
   ```

4. **Build and run with Docker:**

   ```bash
   docker build -t media-app .
   docker run -p 9090:9090 media-app
   ```

5. **Access the health endpoint:**

   Open [http://localhost:9090/health](http://localhost:9090/health)

## Testing

Run tests with:

```bash
pytest
```

## CI/CD Pipeline

This repository utilises GitHub Actions. See [`.github/workflows/ci.yml`](.github/workflows/ci.yml) for details.

## Kubernetes Deployment

Deployment manifests are provided in the `deploy/k8s/` directory.

## Monitoring

Prometheus alert rules are located in the `deploy/monitoring/prometheus-alerts.yml` file.

## Logging

Logging is configured to use JSON format with hostname information for structured logs.

## Licence

This project is released under the MIT Licence.