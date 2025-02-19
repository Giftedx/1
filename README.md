# Media Bot Production-grade System

## Overview

This project provides:

-   A Discord Bot for command processing and Plex integration.
-   A Discord Self-bot for handling video media playback in voice channels.
-   A production-grade architecture with robust error handling, scalability, and an elegant UI dashboard.

## Architecture

The system is designed with a modular architecture, comprising the following key components:

-   **Discord Bot (`src/bot/discord_bot.py`):** Handles command processing and interacts with the Discord API.
-   **Discord Self-bot (`src/discord_selfbot.py`):** Manages media playback in voice channels using a separate Discord account.
-   **Plex Integration (`src/core/plex_manager.py`, `src/plex_server.py`):** Provides seamless integration with Plex Media Server for media library access and playback control.
-   **FFmpeg Management (`src/core/ffmpeg_manager.py`):** Manages FFmpeg processes for media transcoding and streaming.
-   **Redis-based Queue (`src/core/queue_manager.py`):** Implements a distributed queue for managing media playback requests.
-   **Rate Limiting (`src/core/rate_limiter.py`):** Enforces rate limits to prevent abuse and ensure fair usage.
-   **Metrics and Monitoring (`src/metrics.py`, `src/monitoring/`):** Collects and exposes metrics for monitoring system performance and health.
-   **UI Dashboard (`src/ui/`):** Provides a web-based dashboard for monitoring and managing the system.
-   **API (`src/api/`):** Exposes a REST API for interacting with the system.

## Setup

1.  **Environment Variables**

    Create a copy of `.env.example` to `.env` and update the following:

    -   `BOT_TOKEN` or `STREAMING_BOT_TOKEN`: Discord bot token (for bot or selfbot mode).
    -   `PLEX_URL` and `PLEX_TOKEN`: Plex Media Server URL and token.
    -   `REDIS_URL`: Redis connection URL.
    -   `SERVICE_MODE`: Set to either `bot` or `selfbot` to determine which client to run.
    -   `VOICE_CHANNEL_ID` (for selfbot): Discord voice channel ID for the selfbot.
    -   Other configuration options as needed (see `.env.example` for details).

2.  **Dependencies**

    Install Python dependencies:

    ```bash
    pip install -r requirements.txt
    ```

3.  **Local Development**

    To set up a local development environment, it's recommended to use a virtual environment. This isolates the project dependencies from the system-wide Python packages.

    ```bash
    python3 -m venv .venv
    source .venv/bin/activate  # On Linux/macOS
    .venv\Scripts\activate  # On Windows
    pip install -r requirements-dev.txt
    ```

4.  **Linting**

    Run linting to check code style and potential errors:

    ```bash
    flake8 src tests
    ```

5.  **Type Checking**

    Run MyPy to perform static type checking:

    ```bash
    mypy src tests
    ```

6.  **Formatting**

    Use Black and isort to format the code:

    ```bash
    black src tests
    isort src tests
    ```

7.  **Testing**

    Run tests with:

    ```bash
    pytest --maxfail=1 --disable-warnings -q
    ```

## Containerization

1.  **Docker Build**

    Build the Docker image:

    ```bash
    docker build -t media-app .
    ```

    Alternatively, use Docker Compose for building:

    ```bash
    docker-compose build
    ```

2.  **Docker Compose**

    Run the application using Docker Compose:

    ```bash
    docker-compose up
    ```

    To run in detached mode:

    ```bash
    docker-compose up -d
    ```

## UI Dashboard

-   The UI is served from `/ui/index.html` and can be extended as needed.

## Deployment

For production deployment, consider using Kubernetes with this Docker image. Configure resource requests/limits and secret management based on your environment.

## Security

-   Ensure that production tokens and secrets are managed securely (e.g., using Vault or Kubernetes Secrets).
-   Regularly run the provided CI/CD pipeline for security audits.
-   Implement input validation and sanitization to prevent security vulnerabilities.

## Contributing

1.  Fork the repository.
2.  Create a new branch for your feature or bug fix.
3.  Implement your changes and write tests.
4.  Run tests to ensure everything is working correctly.
5.  Submit a pull request.

## License

This project is licensed under the MIT License.
