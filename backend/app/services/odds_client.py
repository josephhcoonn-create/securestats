"""
Async client for The Odds API (https://the-odds-api.com).

Pulls pre-game MLB lines, normalizes each bookmaker's nested response
into one flat dict per (game, book), and matches them to existing
``Game`` rows on (home_team, away_team, date) so they can be persisted
as ``GameOdds``.

Quota
-----
The free tier ships 500 requests/month. Every successful call returns
two response headers we surface via :meth:`OddsClient.get_remaining_quota`:

  - ``x-requests-remaining``: integer; how many calls are left this period
  - ``x-requests-used``: integer; how many we've spent

Logged on every fetch so quota burn is visible in dashboards.
"""
from __future__ import annotations

import logging
from datetime import date as _date
from datetime import datetime
from typing import Any, TypedDict

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.game import Game

logger = logging.getLogger(__name__)


# ─── Constants ───────────────────────────────────────────────────────────────

BASE_URL = "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds/"
DEFAULT_MARKETS = "h2h,spreads,totals"
DEFAULT_REGIONS = "us"
HTTP_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


# ─── Typed shapes ────────────────────────────────────────────────────────────


class FlatOdds(TypedDict):
    """One row's worth of odds — ready for direct insert into GameOdds
    (minus the game_id FK, filled in by match_odds_to_games)."""
    home_team: str
    away_team: str
    commence_time: datetime
    sportsbook: str
    home_moneyline: int | None
    away_moneyline: int | None
    spread_home: float | None
    spread_away: float | None
    over_under: float | None
    fetched_at: datetime


# ─── Errors ──────────────────────────────────────────────────────────────────


class OddsApiError(RuntimeError):
    """Raised when The Odds API returns a non-2xx status."""


class OddsQuotaExhausted(OddsApiError):
    """Raised when the response advertises zero remaining requests."""


# ─── Client ──────────────────────────────────────────────────────────────────


class OddsClient:
    """
    Thin wrapper around The Odds API. Each instance holds the API key and
    an httpx.AsyncClient.

    Use as an async context manager so the connection pool is closed
    cleanly:

        async with OddsClient(api_key) as oc:
            raw = await oc.get_todays_odds()
            remaining = oc.last_remaining_quota
    """

    def __init__(self, api_key: str | None) -> None:
        if not api_key:
            raise OddsApiError(
                "OddsClient requires an API key — set THE_ODDS_API_KEY in .env "
                "(sign up at https://the-odds-api.com)."
            )
        self._api_key = api_key
        self._client = httpx.AsyncClient(timeout=HTTP_TIMEOUT)
        self.last_remaining_quota: int | None = None
        self.last_used_quota: int | None = None

    async def __aenter__(self) -> OddsClient:
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self._client.aclose()

    # ── Public methods ──────────────────────────────────────────────────────

    async def get_todays_odds(
        self,
        markets: str = DEFAULT_MARKETS,
        regions: str = DEFAULT_REGIONS,
    ) -> list[dict[str, Any]]:
        """
        Fetch raw odds for every MLB game with open lines from US books.

        Returns the upstream JSON list verbatim — callers should pipe
        through :func:`parse_odds_response` to get FlatOdds rows.
        """
        params = {
            "apiKey": self._api_key,
            "markets": markets,
            "regions": regions,
            "oddsFormat": "american",
        }
        logger.info("OddsClient: GET %s markets=%s regions=%s", BASE_URL, markets, regions)
        resp = await self._client.get(BASE_URL, params=params)

        # Capture quota headers BEFORE raising — even error responses include them.
        self._capture_quota(resp)

        if resp.status_code == 429 or self.last_remaining_quota == 0:
            raise OddsQuotaExhausted(
                f"Odds API quota exhausted (remaining={self.last_remaining_quota})"
            )
        if resp.status_code >= 400:
            raise OddsApiError(
                f"Odds API returned {resp.status_code}: {resp.text[:200]}"
            )

        data = resp.json()
        if not isinstance(data, list):
            raise OddsApiError(f"unexpected response shape: {type(data).__name__}")

        logger.info(
            "OddsClient: %d games returned; quota remaining=%s used=%s",
            len(data),
            self.last_remaining_quota,
            self.last_used_quota,
        )
        return data

    async def get_remaining_quota(self) -> int | None:
        """
        Return the most recently observed `x-requests-remaining` value.

        Returns None if no request has been made yet. Doesn't burn a
        quota slot — values are pulled from cached headers.
        """
        return self.last_remaining_quota

    # ── Internals ───────────────────────────────────────────────────────────

    def _capture_quota(self, resp: httpx.Response) -> None:
        remaining = resp.headers.get("x-requests-remaining")
        used = resp.headers.get("x-requests-used")
        if remaining is not None:
            try:
                self.last_remaining_quota = int(remaining)
            except ValueError:
                pass
        if used is not None:
            try:
                self.last_used_quota = int(used)
            except ValueError:
                pass


# ─── Parsing ─────────────────────────────────────────────────────────────────


def parse_odds_response(raw: list[dict[str, Any]]) -> list[FlatOdds]:
    """
    Flatten the upstream nested JSON into one FlatOdds dict per
    (game, bookmaker). Markets that aren't present simply leave their
    fields as None — we don't skip the row.
    """
    fetched_at = datetime.utcnow().replace(microsecond=0)
    rows: list[FlatOdds] = []

    for game in raw:
        home_team = game.get("home_team")
        away_team = game.get("away_team")
        commence_str = game.get("commence_time")
        if not (home_team and away_team and commence_str):
            continue
        try:
            commence_time = datetime.fromisoformat(commence_str.replace("Z", "+00:00"))
        except ValueError:
            logger.warning("OddsClient: skipping game with bad commence_time %r", commence_str)
            continue

        for book in game.get("bookmakers", []):
            book_key = book.get("key")
            if not book_key:
                continue

            markets = {m["key"]: m for m in book.get("markets", []) if m.get("key")}
            h2h = markets.get("h2h")
            spreads = markets.get("spreads")
            totals = markets.get("totals")

            home_ml = _outcome_price(h2h, home_team) if h2h else None
            away_ml = _outcome_price(h2h, away_team) if h2h else None

            spread_h = _outcome_point(spreads, home_team) if spreads else None
            spread_a = _outcome_point(spreads, away_team) if spreads else None

            over_under = _outcome_point(totals, "Over") if totals else None

            rows.append(
                FlatOdds(
                    home_team=home_team,
                    away_team=away_team,
                    commence_time=commence_time,
                    sportsbook=book_key,
                    home_moneyline=home_ml,
                    away_moneyline=away_ml,
                    spread_home=spread_h,
                    spread_away=spread_a,
                    over_under=over_under,
                    fetched_at=fetched_at,
                )
            )

    return rows


def _outcome_price(market: dict[str, Any] | None, team_or_label: str) -> int | None:
    """Pull the integer American-odds price for a specific outcome."""
    if not market:
        return None
    for outcome in market.get("outcomes", []):
        if outcome.get("name") == team_or_label:
            price = outcome.get("price")
            try:
                return int(price) if price is not None else None
            except (TypeError, ValueError):
                return None
    return None


def _outcome_point(market: dict[str, Any] | None, team_or_label: str) -> float | None:
    """Pull the spread/total point for a specific outcome."""
    if not market:
        return None
    for outcome in market.get("outcomes", []):
        if outcome.get("name") == team_or_label:
            point = outcome.get("point")
            try:
                return float(point) if point is not None else None
            except (TypeError, ValueError):
                return None
    return None


# ─── Game matching ───────────────────────────────────────────────────────────


async def match_odds_to_games(
    session: AsyncSession,
    rows: list[FlatOdds],
) -> list[tuple[FlatOdds, int]]:
    """
    Resolve each FlatOdds row to a local Game.id.

    Matching key is (home_team, away_team, date(commence_time)). Games
    that don't have a matching local row are skipped with a warning so
    the daily pipeline doesn't die when a new team/franchise name shows
    up before our ETL imports it.

    Returns a list of (row, game_id) tuples for the ones that matched.
    """
    if not rows:
        return []

    # One query per distinct date — usually 1–2, never more than 7
    dates_needed: set[_date] = {r["commence_time"].date() for r in rows}
    games_by_key: dict[tuple[str, str, _date], int] = {}
    for d in dates_needed:
        result = await session.execute(select(Game).where(Game.date == d))
        for game in result.scalars().all():
            games_by_key[(game.home_team, game.away_team, game.date)] = game.id

    matched: list[tuple[FlatOdds, int]] = []
    missing = 0
    for row in rows:
        key = (row["home_team"], row["away_team"], row["commence_time"].date())
        gid = games_by_key.get(key)
        if gid is None:
            missing += 1
            continue
        matched.append((row, gid))

    if missing:
        logger.warning(
            "OddsClient: %d/%d odds rows had no local Game match; "
            "have you run the daily ETL for these dates?",
            missing,
            len(rows),
        )
    return matched
