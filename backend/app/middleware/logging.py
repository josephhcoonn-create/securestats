"""
Structured logging + an access-log middleware that records every
4xx / 5xx response.

`configure_logging()` installs either a plain-text or JSON formatter
based on Settings.log_format. Other modules use `event_logger` to emit
structured business events (auth, etl) — fields are kept first-class
so logs are greppable in either format.

NEVER log passwords or JWTs. The auth endpoints redact accordingly.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from pythonjsonlogger import jsonlogger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings

# ── Setup ────────────────────────────────────────────────────────────────────

_LOG_FMT_TEXT = "%(asctime)s %(levelname)-8s %(name)s - %(message)s"


def configure_logging() -> None:
    """Install the configured formatter on the root logger."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Avoid duplicate handlers when the function is invoked twice
    # (e.g. uvicorn workers, test re-imports).
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler()
    if settings.log_format.lower() == "json":
        handler.setFormatter(
            jsonlogger.JsonFormatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s",
                rename_fields={"asctime": "ts", "levelname": "level"},
            )
        )
    else:
        handler.setFormatter(logging.Formatter(_LOG_FMT_TEXT, datefmt="%H:%M:%S"))
    root.addHandler(handler)


# ── Event logger ─────────────────────────────────────────────────────────────

_event_logger = logging.getLogger("event")


def log_event(category: str, action: str, **fields: Any) -> None:
    """
    Emit a structured business event. In JSON mode each field becomes a
    top-level key; in text mode they become `key=value` suffixes.

    Example:
        log_event("auth", "login_success", username="alice", user_id=7)

    Caller is responsible for not passing secrets.
    """
    extras = {"category": category, "action": action, **fields}
    if settings.log_format.lower() == "json":
        _event_logger.info("", extra=extras)
    else:
        kv = " ".join(f"{k}={v}" for k, v in extras.items())
        _event_logger.info(kv)


# ── Access log middleware ────────────────────────────────────────────────────


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Log every 4xx / 5xx response with method, path, status, duration."""

    async def dispatch(self, request: Request, call_next) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        if response.status_code >= 400:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            log_event(
                "http",
                "error" if response.status_code >= 500 else "client_error",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=duration_ms,
                client=request.client.host if request.client else "unknown",
            )
        return response
