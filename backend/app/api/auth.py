from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt_handler import create_access_token, verify_token
from app.auth.password import hash_password, verify_password
from app.auth.rbac import TokenPayload, bearer_scheme, get_current_user
from app.config import settings
from app.database import get_db
from app.middleware.logging import log_event
from app.middleware.rate_limit import limiter
from app.models.user import User, UserRole
from app.schemas.auth import TokenResponse, UserCreate, UserLogin, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])

# Issue a refreshed token only when the current one is within this
# window of expiring. Stops well-behaved clients from rotating tokens
# on every request and keeps token churn predictable.
_REFRESH_WINDOW_SECONDS = 30 * 60


# ---------------------------------------------------------------------------
# POST /auth/register
# ---------------------------------------------------------------------------


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(settings.rate_limit_register)
async def register(
    request: Request,  # noqa: ARG001 — required by slowapi for key extraction
    body: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    # Check username uniqueness
    existing = await db.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        log_event("auth", "register_conflict", username=body.username, reason="username_taken")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already taken",
        )

    # Check email uniqueness
    existing_email = await db.execute(select(User).where(User.email == body.email))
    if existing_email.scalar_one_or_none():
        log_event("auth", "register_conflict", username=body.username, reason="email_taken")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(
        username=body.username,
        email=body.email,
        hashed_password=hash_password(body.password),
        role=UserRole.viewer,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    log_event("auth", "register_success", username=user.username, user_id=user.id)
    return user


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.rate_limit_login)
async def login(
    request: Request,  # noqa: ARG001 — required by slowapi for key extraction
    body: UserLogin,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    result = await db.execute(select(User).where(User.username == body.username))
    user: User | None = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.hashed_password):
        log_event("auth", "login_failure", username=body.username, reason="invalid_credentials")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        log_event("auth", "login_failure", username=body.username, reason="disabled")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    log_event("auth", "login_success", username=user.username, user_id=user.id, role=user.role.value)
    return TokenResponse(access_token=token)


# ---------------------------------------------------------------------------
# POST /auth/refresh
# ---------------------------------------------------------------------------


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
) -> TokenResponse:
    """
    Issue a new token if the caller's current token is valid AND within
    the refresh window (last 30 min before exp). Returns 400 if the
    token isn't close enough to expiry yet so well-behaved clients don't
    churn tokens on every request.
    """
    try:
        payload = verify_token(credentials.credentials)
    except JWTError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from err

    exp_ts = payload.get("exp")
    sub = payload.get("sub")
    role_str = payload.get("role")
    if exp_ts is None or sub is None or role_str is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing required claims",
        )

    seconds_until_exp = exp_ts - int(datetime.now(UTC).timestamp())
    if seconds_until_exp > _REFRESH_WINDOW_SECONDS:
        # Token still has plenty of life left — refresh refused.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Token still valid for {seconds_until_exp}s; "
                f"refresh allowed within {_REFRESH_WINDOW_SECONDS}s of expiry."
            ),
        )

    new_token = create_access_token({"sub": sub, "role": role_str})
    log_event("auth", "token_refresh", user_id=int(sub), role=role_str)
    return TokenResponse(access_token=new_token)


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------


@router.get("/me", response_model=UserResponse)
async def me(
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    result = await db.execute(select(User).where(User.id == current_user.user_id))
    user: User | None = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user
