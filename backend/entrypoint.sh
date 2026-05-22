#!/bin/sh
# SecureStats backend entrypoint.
#
# 1. Wait briefly for Postgres (compose healthcheck already gates the
#    container's start, but psycopg can still race the readiness probe).
# 2. Run pending Alembic migrations.
# 3. Hand off to uvicorn (exec so it gets PID 1 and signals propagate).
set -e

echo "[entrypoint] Running Alembic migrations…"
alembic upgrade head

echo "[entrypoint] Starting uvicorn on 0.0.0.0:8000"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 "$@"
