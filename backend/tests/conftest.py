"""
Pytest fixtures for SecureStats test suite.

Windows note: psycopg async requires SelectorEventLoop. The policy is set at
module import time so pytest-asyncio picks it up before creating any loop.
"""
import asyncio
import sys

# ── Windows event loop fix (must be before any asyncio usage) ────────────────
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import pytest
import pytest_asyncio
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Test database URLs ────────────────────────────────────────────────────────
_TEST_ASYNC_URL = "postgresql+psycopg://securestats:changeme@localhost:5432/securestats_test"
_TEST_SYNC_URL = "postgresql+psycopg://securestats:changeme@localhost:5432/securestats_test"
_ADMIN_SYNC_URL = "postgresql+psycopg://securestats:changeme@localhost:5432/postgres"

# ── Override settings before any app module imports it ───────────────────────
from app.config import settings  # noqa: E402

settings.database_url = _TEST_ASYNC_URL
# Tests share a process; per-IP rate limits would tank the suite the
# moment a single test class hits /login more than 5 times. Disable.
settings.rate_limit_enabled = False

# ── App + DB imports (after settings override) ────────────────────────────────
import app.models  # noqa: F401, E402 — registers all models on Base.metadata
from app.auth.jwt_handler import create_access_token  # noqa: E402
from app.auth.password import hash_password  # noqa: E402
from app.auth.rbac import TokenPayload, require_role  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402

# ── Create securestats_test database if it doesn't exist ─────────────────────
try:
    import psycopg  # type: ignore

    with psycopg.connect(_ADMIN_SYNC_URL.replace("+psycopg", ""), autocommit=True) as _conn:
        _conn.execute("CREATE DATABASE securestats_test")
except Exception:
    pass  # Already exists or superuser not needed — tables created below

# ── Async engine for tests ────────────────────────────────────────────────────
test_engine = create_async_engine(_TEST_ASYNC_URL, echo=False)
TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)

# ── Add analyst-only test route so RBAC tests have something to hit ───────────
@app.get("/api/v1/test/analyst-only")
async def _analyst_route(
    _: TokenPayload = Depends(require_role(UserRole.analyst)),
):
    return {"access": "granted"}


# ── Session-scoped: create / drop all tables once per pytest run ──────────────
@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Create all tables synchronously once; drop them after the session."""
    sync_engine = create_engine(_TEST_SYNC_URL)
    Base.metadata.create_all(sync_engine)
    yield
    Base.metadata.drop_all(sync_engine)
    sync_engine.dispose()


# ── Function-scoped: wipe table rows after every test ────────────────────────
@pytest_asyncio.fixture(autouse=True)
async def clean_tables():
    yield
    async with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())


# ── Test HTTP client with get_db override ────────────────────────────────────
@pytest_asyncio.fixture
async def client() -> AsyncClient:
    async def _override_get_db() -> AsyncSession:
        async with TestSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


# ── User fixtures ─────────────────────────────────────────────────────────────
@pytest_asyncio.fixture
async def viewer_user(client: AsyncClient) -> dict:
    """Register a viewer via the API and return the response dict."""
    resp = await client.post(
        "/api/v1/auth/register",
        json={"username": "viewer_test", "email": "viewer@test.com", "password": "Testpass123"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest_asyncio.fixture
async def analyst_user() -> dict:
    """Create an analyst user directly in the DB (bypasses register endpoint)."""
    async with TestSessionLocal() as session:
        user = User(
            username="analyst_test",
            email="analyst@test.com",
            hashed_password=hash_password("Testpass123"),
            role=UserRole.analyst,
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return {"id": user.id, "username": user.username, "role": user.role.value}


@pytest_asyncio.fixture
async def admin_user() -> dict:
    """Create an admin user directly in the DB."""
    async with TestSessionLocal() as session:
        user = User(
            username="admin_test",
            email="admin@test.com",
            hashed_password=hash_password("Testpass123"),
            role=UserRole.admin,
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return {"id": user.id, "username": user.username, "role": user.role.value}


# ── Auth header fixtures ──────────────────────────────────────────────────────
@pytest_asyncio.fixture
async def viewer_headers(viewer_user: dict) -> dict:
    token = create_access_token({"sub": str(viewer_user["id"]), "role": "viewer"})
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def analyst_headers(analyst_user: dict) -> dict:
    token = create_access_token({"sub": str(analyst_user["id"]), "role": "analyst"})
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def admin_headers(admin_user: dict) -> dict:
    token = create_access_token({"sub": str(admin_user["id"]), "role": "admin"})
    return {"Authorization": f"Bearer {token}"}
