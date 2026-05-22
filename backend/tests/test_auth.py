"""
Auth endpoint tests — Phase 2.3

Covers:
- Registration (success, duplicate username, duplicate email)
- Login (success + token claims, wrong password, nonexistent user)
- Protected endpoint access (no token, valid token, invalid token)
- RBAC role enforcement (viewer blocked from analyst route, analyst/admin pass)
"""
import pytest
from httpx import AsyncClient
from jose import jwt

from app.config import settings

# ══════════════════════════════════════════════════════════════════════════════
# Registration
# ══════════════════════════════════════════════════════════════════════════════


class TestRegistration:
    async def test_register_success(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/auth/register",
            json={"username": "newuser", "email": "new@test.com", "password": "testpass123"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == "newuser"
        assert data["email"] == "new@test.com"
        assert data["role"] == "viewer"
        assert data["is_active"] is True
        # Password must never appear in the response
        assert "password" not in data
        assert "hashed_password" not in data

    async def test_register_duplicate_username(self, client: AsyncClient):
        payload = {"username": "dupuser", "email": "first@test.com", "password": "testpass123"}
        await client.post("/api/v1/auth/register", json=payload)

        resp = await client.post(
            "/api/v1/auth/register",
            json={"username": "dupuser", "email": "second@test.com", "password": "testpass123"},
        )
        assert resp.status_code == 409
        assert "Username" in resp.json()["detail"]

    async def test_register_duplicate_email(self, client: AsyncClient):
        await client.post(
            "/api/v1/auth/register",
            json={"username": "user_a", "email": "shared@test.com", "password": "testpass123"},
        )
        resp = await client.post(
            "/api/v1/auth/register",
            json={"username": "user_b", "email": "shared@test.com", "password": "testpass123"},
        )
        assert resp.status_code == 409
        assert "Email" in resp.json()["detail"]

    async def test_register_short_password(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/auth/register",
            json={"username": "shortpw", "email": "short@test.com", "password": "abc"},
        )
        assert resp.status_code == 422

    async def test_register_invalid_email(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/auth/register",
            json={"username": "bademail", "email": "not-an-email", "password": "testpass123"},
        )
        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# Login
# ══════════════════════════════════════════════════════════════════════════════


class TestLogin:
    async def test_login_success_and_token_claims(
        self, client: AsyncClient, viewer_user: dict
    ):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "viewer_test", "password": "testpass123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

        # Decode and verify all required claims
        payload = jwt.decode(
            data["access_token"],
            settings.secret_key,
            algorithms=[settings.algorithm],
        )
        assert payload["sub"] == str(viewer_user["id"])
        assert payload["role"] == "viewer"
        assert "exp" in payload

    async def test_login_wrong_password(self, client: AsyncClient, viewer_user: dict):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "viewer_test", "password": "wrongpassword"},
        )
        assert resp.status_code == 401

    async def test_login_nonexistent_user(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "ghost_user", "password": "testpass123"},
        )
        assert resp.status_code == 401

    async def test_login_case_sensitive_username(self, client: AsyncClient, viewer_user: dict):
        """Username lookup must be exact — 'Viewer_Test' is not 'viewer_test'."""
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "Viewer_Test", "password": "testpass123"},
        )
        assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# Protected endpoints
# ══════════════════════════════════════════════════════════════════════════════


class TestProtectedEndpoints:
    async def test_me_no_token_returns_403(self, client: AsyncClient):
        """FastAPI's HTTPBearer returns 403 when Authorization header is absent."""
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 403

    async def test_me_invalid_token_returns_401(self, client: AsyncClient):
        resp = await client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer this.is.garbage"}
        )
        assert resp.status_code == 401

    async def test_me_valid_token_returns_user(
        self, client: AsyncClient, viewer_headers: dict, viewer_user: dict
    ):
        resp = await client.get("/api/v1/auth/me", headers=viewer_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == viewer_user["id"]
        assert data["username"] == "viewer_test"
        assert data["role"] == "viewer"
        assert "hashed_password" not in data


# ══════════════════════════════════════════════════════════════════════════════
# RBAC role enforcement
# ══════════════════════════════════════════════════════════════════════════════


class TestRBAC:
    """
    Uses the /api/v1/test/analyst-only route registered in conftest.py
    which requires UserRole.analyst minimum.
    """

    ANALYST_ROUTE = "/api/v1/test/analyst-only"

    async def test_viewer_blocked_from_analyst_route(
        self, client: AsyncClient, viewer_headers: dict
    ):
        resp = await client.get(self.ANALYST_ROUTE, headers=viewer_headers)
        assert resp.status_code == 403
        assert "Insufficient permissions" in resp.json()["detail"]

    async def test_analyst_can_access_analyst_route(
        self, client: AsyncClient, analyst_headers: dict
    ):
        resp = await client.get(self.ANALYST_ROUTE, headers=analyst_headers)
        assert resp.status_code == 200
        assert resp.json()["access"] == "granted"

    async def test_admin_can_access_analyst_route(
        self, client: AsyncClient, admin_headers: dict
    ):
        """Admin rank > analyst rank so access must be granted."""
        resp = await client.get(self.ANALYST_ROUTE, headers=admin_headers)
        assert resp.status_code == 200

    async def test_no_token_blocked_from_analyst_route(self, client: AsyncClient):
        resp = await client.get(self.ANALYST_ROUTE)
        assert resp.status_code == 403
