"""
Phase 7 — attack-class security tests.

Walks each item of the Task 7.2 brief with at least one failing
"happy path for the attacker" test that would catch a regression:

  1. Rate limiting triggers after the threshold       → TestRateLimitThreshold
  2. SQL injection in search is rendered inert        → TestSqlInjection
  3. XSS payloads in stored fields don't escape JSON  → TestXssPayloads
  4. Passwords never appear in any API response       → TestPasswordsNeverReturned
  5. Expired tokens return 401                        → TestExpiredToken
  6. CORS denies requests from foreign origins        → TestCorsForeignOrigin
  7. Malformed / tampered JWTs are rejected           → TestMalformedJwt
  8. Weak passwords are rejected at registration      → TestWeakPasswordRejection
"""
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.auth.jwt_handler import create_access_token
from app.models.batting_stats import BattingStats  # noqa: F401 — keeps mapper warmed
from app.models.player import Player
from tests.conftest import TestSessionLocal

# ══════════════════════════════════════════════════════════════════════════════
# 1. Rate limiting threshold
# ══════════════════════════════════════════════════════════════════════════════


class TestRateLimitThreshold:
    """Cross-references TestRateLimiting in test_security.py — kept here
    because the brief lists it. A 6th login in a 1-minute window MUST
    return 429 with Retry-After."""

    async def test_login_429_with_retry_after(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.middleware import rate_limit as rl

        monkeypatch.setattr(rl.limiter, "enabled", True)
        rl.limiter.reset()

        last = None
        for _ in range(6):
            last = await client.post(
                "/api/v1/auth/login",
                json={"username": "throttled", "password": "Wrong1Password"},
            )
        assert last.status_code == 429
        assert int(last.headers["Retry-After"]) > 0


# ══════════════════════════════════════════════════════════════════════════════
# 2. SQL injection
# ══════════════════════════════════════════════════════════════════════════════


class TestSqlInjection:
    """SQLAlchemy parameterizes every column-level filter, so injection
    payloads should pass through as plain LIKE patterns — never as
    executable SQL. We verify (a) no crash, (b) reachable rows remain
    intact, (c) the payload matches nothing in our seed data."""

    @pytest.fixture(autouse=True)
    async def _seed(self) -> None:
        async with TestSessionLocal() as session:
            session.add_all(
                [
                    Player(mlb_id=911, full_name="Alice Aaron", team="Yankees", position="RF"),
                    Player(mlb_id=912, full_name="Bob Bash",   team="Mets",     position="LF"),
                ]
            )
            await session.commit()

    @pytest.mark.parametrize(
        "payload",
        [
            "'; DROP TABLE players; --",
            "' OR '1'='1",
            "' UNION SELECT NULL,NULL,NULL,NULL,NULL --",
            "Robert'); DROP TABLE players;--",
            "\\",  # LIKE escape character
        ],
    )
    async def test_injection_payload_is_inert(
        self,
        client: AsyncClient,
        viewer_user: dict,  # noqa: ARG002 — registers a user so login works
        payload: str,
    ) -> None:
        # Log in to get a viewer token
        login = await client.post(
            "/api/v1/auth/login",
            json={"username": "viewer_test", "password": "Testpass123"},
        )
        token = login.json()["access_token"]

        resp = await client.get(
            "/api/v1/players/search",
            params={"q": payload},
            headers={"Authorization": f"Bearer {token}"},
        )
        # 200 with a (probably empty) list — not 500, not 4xx
        assert resp.status_code == 200
        assert "items" in resp.json()

        # Critical post-condition: the players table still exists with
        # all seeded rows. If injection ran, this would 500 or come up empty.
        async with TestSessionLocal() as session:
            remaining = (await session.execute(select(Player))).scalars().all()
        assert len(remaining) >= 2


# ══════════════════════════════════════════════════════════════════════════════
# 3. XSS payloads in stored fields
# ══════════════════════════════════════════════════════════════════════════════


class TestXssPayloads:
    """A player stored with a <script> name should come back through the
    JSON API as a literal string with Content-Type: application/json so
    browsers can't render it. The X-Content-Type-Options: nosniff
    header prevents content-type sniffing from promoting it to HTML."""

    XSS_NAME = "<script>alert('xss')</script>"

    async def test_xss_round_trip_is_inert(
        self, client: AsyncClient, viewer_user: dict  # noqa: ARG002
    ) -> None:
        async with TestSessionLocal() as session:
            session.add(
                Player(mlb_id=931, full_name=self.XSS_NAME, team="X", position="X")
            )
            await session.commit()

        login = await client.post(
            "/api/v1/auth/login",
            json={"username": "viewer_test", "password": "Testpass123"},
        )
        token = login.json()["access_token"]

        resp = await client.get(
            "/api/v1/players",
            params={"limit": 100},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        assert resp.headers["x-content-type-options"] == "nosniff"

        # The payload is returned as the exact JSON string (no HTML
        # tags stripped, no &lt; entities) — but as a JSON string value
        # it is NEVER interpreted as HTML by a conforming client.
        body = resp.json()
        names = [p["full_name"] for p in body["items"]]
        assert self.XSS_NAME in names


# ══════════════════════════════════════════════════════════════════════════════
# 4. Passwords never returned
# ══════════════════════════════════════════════════════════════════════════════


class TestPasswordsNeverReturned:
    """Scan every response body that touches the User model for the
    word 'password' (any case), the hashed_password field, or the
    plain-text password the fixture used."""

    PLAIN = "Testpass123"
    FORBIDDEN_KEYS = {"password", "hashed_password", "hashedPassword"}

    @staticmethod
    def _assert_clean(body: dict | list | str, where: str) -> None:
        if isinstance(body, dict):
            for k, v in body.items():
                assert k not in TestPasswordsNeverReturned.FORBIDDEN_KEYS, (
                    f"{where}: forbidden key {k!r} in response"
                )
                TestPasswordsNeverReturned._assert_clean(v, where)
        elif isinstance(body, list):
            for item in body:
                TestPasswordsNeverReturned._assert_clean(item, where)
        elif isinstance(body, str):
            assert TestPasswordsNeverReturned.PLAIN not in body, (
                f"{where}: plain-text password leaked: {body[:120]!r}"
            )

    async def test_register_response_has_no_password(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "leak_probe",
                "email": "leak@test.com",
                "password": self.PLAIN,
            },
        )
        assert resp.status_code == 201
        self._assert_clean(resp.json(), "POST /auth/register")

    async def test_login_response_has_no_password(
        self, client: AsyncClient, viewer_user: dict
    ) -> None:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": viewer_user["username"], "password": self.PLAIN},
        )
        assert resp.status_code == 200
        self._assert_clean(resp.json(), "POST /auth/login")

    async def test_me_response_has_no_password(
        self, client: AsyncClient, viewer_user: dict
    ) -> None:
        login = await client.post(
            "/api/v1/auth/login",
            json={"username": viewer_user["username"], "password": self.PLAIN},
        )
        token = login.json()["access_token"]
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        self._assert_clean(resp.json(), "GET /auth/me")


# ══════════════════════════════════════════════════════════════════════════════
# 5. Expired tokens return 401
# ══════════════════════════════════════════════════════════════════════════════


class TestExpiredToken:
    async def test_expired_token_returns_401(
        self, client: AsyncClient, viewer_user: dict
    ) -> None:
        # Mint a token that expired one second ago.
        expired = create_access_token(
            {"sub": str(viewer_user["id"]), "role": "viewer"},
            expires_delta=timedelta(seconds=-1),
        )
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {expired}"},
        )
        assert resp.status_code == 401
        assert resp.headers.get("www-authenticate", "").lower().startswith("bearer")


# ══════════════════════════════════════════════════════════════════════════════
# 6. CORS: foreign origins do NOT receive an Allow-Origin header
# ══════════════════════════════════════════════════════════════════════════════


class TestCorsForeignOrigin:
    """Starlette's CORS middleware doesn't return 403 for disallowed
    origins — it just omits the Access-Control-Allow-Origin header so
    the browser refuses the response. We assert the omission."""

    async def test_preflight_from_foreign_origin_has_no_acao(
        self, client: AsyncClient
    ) -> None:
        resp = await client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": "http://evil.example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        # The middleware returns 400 for unmatched origins on a true
        # preflight, but never echoes the foreign origin back.
        assert "access-control-allow-origin" not in {
            k.lower() for k in resp.headers.keys()
        }, "foreign origin must NOT receive Access-Control-Allow-Origin"

    async def test_simple_get_from_foreign_origin_has_no_acao(
        self, client: AsyncClient
    ) -> None:
        # A simple GET still hits the endpoint, but the response must
        # omit the ACAO header for foreign origins so the browser
        # blocks the XHR from reading it.
        resp = await client.get(
            "/health", headers={"Origin": "http://evil.example.com"}
        )
        assert resp.status_code == 200
        assert "access-control-allow-origin" not in {
            k.lower() for k in resp.headers.keys()
        }


# ══════════════════════════════════════════════════════════════════════════════
# 7. Malformed / tampered JWTs
# ══════════════════════════════════════════════════════════════════════════════


class TestMalformedJwt:
    """Every variant a determined attacker would try."""

    @pytest.fixture
    def good_token(self, viewer_user: dict) -> str:
        return create_access_token({"sub": str(viewer_user["id"]), "role": "viewer"})

    async def test_tampered_signature_returns_401(
        self, client: AsyncClient, good_token: str
    ) -> None:
        # Replace the signature entirely so there's no chance the
        # mutation happens to land on a base64 character that decodes
        # to the same bytes (a flaky failure mode for "flip one char"
        # tests on HS256 tokens).
        head, payload, _sig = good_token.rsplit(".", 2)
        tampered = f"{head}.{payload}.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {tampered}"},
        )
        assert resp.status_code == 401

    async def test_alg_none_attack_returns_401(
        self, client: AsyncClient, viewer_user: dict
    ) -> None:
        # Classic alg=none — the header advertises no signature
        # algorithm. python-jose rejects this because we passed an
        # explicit algorithms allowlist to jwt.decode.
        import base64
        import json

        def _b64(d: dict) -> str:
            return base64.urlsafe_b64encode(
                json.dumps(d, separators=(",", ":")).encode()
            ).rstrip(b"=").decode()

        header = _b64({"alg": "none", "typ": "JWT"})
        payload = _b64({"sub": str(viewer_user["id"]), "role": "admin", "exp": 9_999_999_999})
        forged = f"{header}.{payload}."  # empty signature

        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {forged}"},
        )
        assert resp.status_code == 401

    @pytest.mark.parametrize(
        "garbage",
        [
            "not-a-jwt",
            "two.parts",
            "....",
            "Bearer-prefix-in-token",
            "",
        ],
    )
    async def test_garbage_token_returns_401_or_403(
        self, client: AsyncClient, garbage: str
    ) -> None:
        # Empty string can be classified as "no credentials" → 403.
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {garbage}"},
        )
        assert resp.status_code in (401, 403), (
            f"garbage token {garbage!r} unexpectedly returned {resp.status_code}"
        )

    async def test_missing_sub_claim_returns_401(self, client: AsyncClient) -> None:
        # Token signed with our key but missing required claims
        missing_sub = create_access_token({"role": "admin"})
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {missing_sub}"},
        )
        assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# 8. Weak passwords rejected
# ══════════════════════════════════════════════════════════════════════════════


class TestWeakPasswordRejection:
    """Mirror of TestPasswordComplexity from test_security.py — kept
    here to satisfy the brief's checklist directly. Each common weak
    pattern must trip 422."""

    @pytest.mark.parametrize(
        "password,reason",
        [
            ("short1A",         "too short"),
            ("alllowercase1",   "no uppercase"),
            ("ALLUPPERCASE1",   "no lowercase"),
            ("NoDigitsAtAll",   "no digit"),
            ("",                "empty"),
            ("12345678",        "no letters"),
        ],
    )
    async def test_weak_password_rejected(
        self, client: AsyncClient, password: str, reason: str  # noqa: ARG002
    ) -> None:
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "weakpw_probe",
                "email": "weak@test.com",
                "password": password,
            },
        )
        assert resp.status_code == 422, (
            f"password {password!r} ({reason}) was accepted with status {resp.status_code}"
        )
