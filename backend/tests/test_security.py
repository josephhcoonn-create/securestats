"""
Phase 7 — security hardening tests.

Covers:
- Password complexity (case + digit requirements)
- Username regex
- Rate limiting (toggle-on roundtrip + 429 envelope)
- Token refresh window (too-early refusal + close-to-expiry success)
- Security headers attached to every response
- CORS preflight allowing the configured origin
"""
from datetime import timedelta

import pytest
from httpx import AsyncClient
from jose import jwt

from app.auth.jwt_handler import create_access_token
from app.config import settings

# ══════════════════════════════════════════════════════════════════════════════
# Password complexity + username regex
# ══════════════════════════════════════════════════════════════════════════════


class TestPasswordComplexity:
    @pytest.mark.parametrize(
        "password,expected_word",
        [
            ("nodigits!Aa", "digit"),
            ("nouppercase1", "uppercase"),
            ("NOLOWERCASE1", "lowercase"),
            ("Sho1", "8 characters"),
        ],
    )
    async def test_weak_passwords_rejected(
        self, client: AsyncClient, password: str, expected_word: str
    ) -> None:
        resp = await client.post(
            "/api/v1/auth/register",
            json={"username": "weakpw", "email": "weak@test.com", "password": password},
        )
        assert resp.status_code == 422
        body_str = resp.text.lower()
        assert expected_word.lower() in body_str

    async def test_complex_password_accepted(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/register",
            json={"username": "complex", "email": "c@test.com", "password": "Strong1Pass"},
        )
        assert resp.status_code == 201


class TestUsernameRegex:
    @pytest.mark.parametrize("bad", ["has space", "weird*chars", "x" * 51, "ab"])
    async def test_bad_usernames_rejected(self, client: AsyncClient, bad: str) -> None:
        resp = await client.post(
            "/api/v1/auth/register",
            json={"username": bad, "email": "u@test.com", "password": "Strong1Pass"},
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize("good", ["alice", "alice_bob", "alice-2026", "AliceB"])
    async def test_good_usernames_accepted(self, client: AsyncClient, good: str) -> None:
        resp = await client.post(
            "/api/v1/auth/register",
            json={"username": good, "email": f"{good}@test.com", "password": "Strong1Pass"},
        )
        assert resp.status_code == 201


# ══════════════════════════════════════════════════════════════════════════════
# Rate limiting
# ══════════════════════════════════════════════════════════════════════════════


class TestRateLimiting:
    """The limiter is force-disabled in conftest. We enable it for this
    single test to verify the 429 path works end-to-end without
    poisoning every other test."""

    async def test_login_returns_429_after_limit(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.middleware import rate_limit as rl

        monkeypatch.setattr(rl.limiter, "enabled", True)
        # Wipe in-memory counters so previous tests don't bleed in
        rl.limiter.reset()

        # 5/minute is the limit; 6th should 429
        last_status = None
        for _ in range(6):
            resp = await client.post(
                "/api/v1/auth/login",
                json={"username": "ratelimit_probe", "password": "Wrong1Password"},
            )
            last_status = resp.status_code

        assert last_status == 429, f"expected 429 after 6 attempts, got {last_status}"
        assert "Retry-After" in resp.headers
        assert int(resp.headers["Retry-After"]) > 0
        assert "rate limit exceeded" in resp.text.lower()


# ══════════════════════════════════════════════════════════════════════════════
# /auth/refresh
# ══════════════════════════════════════════════════════════════════════════════


class TestTokenRefresh:
    async def test_refresh_too_early_returns_400(
        self, client: AsyncClient, viewer_user: dict
    ) -> None:
        # Login to get a fresh token (default 30-min lifetime). It's
        # well outside the refresh window (also 30 min), so refuse.
        login = await client.post(
            "/api/v1/auth/login",
            json={"username": viewer_user["username"], "password": "Testpass123"},
        )
        token = login.json()["access_token"]
        resp = await client.post(
            "/api/v1/auth/refresh",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert "still valid" in resp.text.lower()

    async def test_refresh_near_expiry_returns_new_token(
        self, client: AsyncClient, viewer_user: dict
    ) -> None:
        # Mint a token expiring in 5 minutes — inside the 30-minute window
        near_expiry = create_access_token(
            {"sub": str(viewer_user["id"]), "role": "viewer"},
            expires_delta=timedelta(minutes=5),
        )
        resp = await client.post(
            "/api/v1/auth/refresh",
            headers={"Authorization": f"Bearer {near_expiry}"},
        )
        assert resp.status_code == 200
        new_token = resp.json()["access_token"]
        assert new_token != near_expiry

        # New token must carry the same subject and a later exp
        decoded = jwt.decode(new_token, settings.secret_key, algorithms=[settings.algorithm])
        old_decoded = jwt.decode(near_expiry, settings.secret_key, algorithms=[settings.algorithm])
        assert decoded["sub"] == old_decoded["sub"]
        assert decoded["exp"] > old_decoded["exp"]

    async def test_refresh_without_token_returns_403(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/auth/refresh")
        # HTTPBearer returns 403 when the Authorization header is absent
        assert resp.status_code == 403

    async def test_refresh_with_garbage_token_returns_401(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/refresh",
            headers={"Authorization": "Bearer not-a-real-jwt"},
        )
        assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# Security headers
# ══════════════════════════════════════════════════════════════════════════════


class TestSecurityHeaders:
    async def test_headers_present_on_health(self, client: AsyncClient) -> None:
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["X-XSS-Protection"] == "1; mode=block"
        assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert "camera=()" in resp.headers["Permissions-Policy"]

    async def test_hsts_skipped_in_development(self, client: AsyncClient) -> None:
        resp = await client.get("/health")
        # Default test environment is "development" → no HSTS
        assert "Strict-Transport-Security" not in resp.headers


# ══════════════════════════════════════════════════════════════════════════════
# CORS
# ══════════════════════════════════════════════════════════════════════════════


class TestCORS:
    async def test_allowed_origin_preflight(self, client: AsyncClient) -> None:
        resp = await client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert resp.status_code == 200
        assert resp.headers["access-control-allow-origin"] == "http://localhost:5173"
        # Method allowlist should explicitly include POST
        assert "POST" in resp.headers["access-control-allow-methods"]
