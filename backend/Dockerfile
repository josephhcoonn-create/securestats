# syntax=docker/dockerfile:1.7
FROM python:3.11-slim

# Quieter, snappier Python + cleaner pip output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Minimal system deps:
#   curl  → healthcheck without pulling in a Python stack
#   build-essential / libpq is NOT needed: psycopg[binary] ships wheels.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Install Python deps first so this layer caches across code changes
COPY requirements.txt .
RUN pip install -r requirements.txt

# App code + migration scripts + entrypoint
COPY app/          ./app/
COPY alembic/      ./alembic/
COPY alembic.ini   ./alembic.ini
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

# Run as non-root for defense in depth
RUN useradd --create-home --uid 1000 appuser \
 && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]
