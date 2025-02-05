# Media Bot Production‑Grade System

## Overview

This project provides:

- A Discord Bot for command processing and Plex integration.
- A Discord Self‑bot for handling video media playback in voice channels.
- A production‑grade architecture with robust error handling, scalability, and an elegant UI dashboard.

## Setup

1. **Environment Variables**  
   Create a copy of `.env.example` to `.env` and update the following:

   - `BOT_TOKEN` or `STREAMING_BOT_TOKEN`
   - `PLEX_URL` and `PLEX_TOKEN`
   - `REDIS_URL`
   - `SERVICE_MODE` (set to either `bot` or `selfbot`)
   - `VOICE_CHANNEL_ID` (for selfbot)

2. **Dependencies**  
   Install Python dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. **Testing**
   Run tests with:
   ```bash
   pytest --maxfail=1 --disable-warnings -q
   ```

## Containerization

1. **Docker Build**

   ```bash
   docker build -t media-app .
   ```

2. **Docker Compose**
   ```bash
   docker-compose up
   ```

## UI Dashboard

- The UI is served from `/ui/index.html` and can be extended as needed.

## Deployment

For production deployment, consider using Kubernetes with this Docker image. Configure resource requests/limits and secret management based on your environment.

## Security

- Ensure that production tokens and secrets are managed securely (e.g., using Vault or Kubernetes Secrets).
- Regularly run the provided CI/CD pipeline for security audits.
