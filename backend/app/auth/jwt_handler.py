from datetime import UTC, datetime, timedelta
from typing import Any

from jose import jwt

from app.config import settings


def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """
    Create a signed JWT.

    The payload must include at least ``sub`` (user_id as str) and ``role``.
    An ``exp`` claim is added automatically.
    """
    to_encode = data.copy()
    expire = datetime.now(UTC) + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def verify_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a JWT.

    Returns the payload dict on success.
    Raises ``JWTError`` (from python-jose) on any failure so callers can
    translate it into an appropriate HTTP response.
    """
    return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
