"""
Per-IP rate limiting for the API.

Hot endpoints (login, register) get tighter limits than the bulk
analytics endpoints. The limiter can be disabled in test environments
via Settings.rate_limit_enabled.

Usage at the route level:

    from app.middleware.rate_limit import limiter
    from app.config import settings

    @router.post("/login")
    @limiter.limit(settings.rate_limit_login)
    async def login(request: Request, ...): ...

The `request: Request` parameter is mandatory — slowapi extracts the
client IP from it via `get_remote_address`.
"""
from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings


def _client_ip(request: Request) -> str:
    """
    Prefer the leftmost X-Forwarded-For when present so the nginx proxy
    in docker-compose doesn't make every request appear to come from a
    single internal IP.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(
    key_func=_client_ip,
    enabled=settings.rate_limit_enabled,
    default_limits=[settings.rate_limit_default],
    # headers_enabled=True would auto-inject X-RateLimit-* headers but
    # requires every decorated endpoint to accept a `response: Response`
    # parameter and return it. Keeping False preserves the simpler
    # signature; clients still get 429 + Retry-After on overage.
    headers_enabled=False,
)


def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """
    Custom 429 handler — slowapi's default returns a plain string; ours
    returns JSON with the same envelope as our other errors and includes
    Retry-After.
    """
    retry_after = getattr(exc, "retry_after", 60)
    detail = (
        f"Rate limit exceeded: {exc.detail}. Retry after {retry_after} seconds."
    )
    return JSONResponse(
        status_code=429,
        content={"detail": detail},
        headers={"Retry-After": str(retry_after)},
    )
