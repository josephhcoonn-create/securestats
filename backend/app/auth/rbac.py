from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from app.auth.jwt_handler import verify_token
from app.models.user import UserRole

# ---------------------------------------------------------------------------
# Role hierarchy — higher index = more privileged
# ---------------------------------------------------------------------------
ROLE_HIERARCHY: dict[UserRole, int] = {
    UserRole.viewer: 0,
    UserRole.analyst: 1,
    UserRole.admin: 2,
}

bearer_scheme = HTTPBearer()

# ---------------------------------------------------------------------------
# Shared payload type returned by get_current_user
# ---------------------------------------------------------------------------


class TokenPayload:
    def __init__(self, user_id: int, role: UserRole) -> None:
        self.user_id = user_id
        self.role = role


# ---------------------------------------------------------------------------
# Base dependency: validate JWT and return TokenPayload
# ---------------------------------------------------------------------------


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
) -> TokenPayload:
    """
    Extract and validate the JWT from the ``Authorization: Bearer <token>`` header.
    Returns a :class:`TokenPayload` on success; raises HTTP 401 on any failure.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = verify_token(credentials.credentials)
        user_id: str | None = payload.get("sub")
        role_str: str | None = payload.get("role")
        if user_id is None or role_str is None:
            raise credentials_exception
        role = UserRole(role_str)
    except (JWTError, ValueError):
        raise credentials_exception

    return TokenPayload(user_id=int(user_id), role=role)


# ---------------------------------------------------------------------------
# RBAC dependency factory: require a minimum role level
# ---------------------------------------------------------------------------


def require_role(minimum_role: UserRole):
    """
    Returns a FastAPI dependency that enforces a minimum role.

    Usage::

        @router.get("/admin-only")
        async def admin_endpoint(
            _: Annotated[TokenPayload, Depends(require_role(UserRole.admin))]
        ): ...
    """

    async def _check_role(
        current_user: Annotated[TokenPayload, Depends(get_current_user)],
    ) -> TokenPayload:
        if ROLE_HIERARCHY.get(current_user.role, -1) < ROLE_HIERARCHY[minimum_role]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Insufficient permissions. "
                    f"Required: {minimum_role.value}, "
                    f"yours: {current_user.role.value}"
                ),
            )
        return current_user

    return _check_role
