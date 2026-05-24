"""
Tests for the OddsClient + parser + Game matcher.

The Odds API never gets called for real — every HTTP request is
intercepted via respx so the suite runs offline and doesn't burn
the 500-req/month quota.
"""
from datetime import date as _date
from datetime import datetime

import httpx
import pytest
import respx

from app.models.game import Game
from app.services.odds_client import (
    BASE_URL,
    OddsApiError,
    OddsClient,
    OddsQuotaExhausted,
    match_odds_to_games,
    parse_odds_response,
)
from tests.conftest import TestSessionLocal

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_response() -> list[dict]:
    """One MLB game with two bookmakers and all three markets — the
    minimum non-trivial shape The Odds API returns."""
    return [
        {
            "id": "abc",
            "sport_key": "baseball_mlb",
            "commence_time": "2026-05-22T23:05:00Z",
            "home_team": "New York Yankees",
            "away_team": "Boston Red Sox",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "title": "DraftKings",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "New York Yankees", "price": -150},
                                {"name": "Boston Red Sox", "price": 130},
                            ],
                        },
                        {
                            "key": "spreads",
                            "outcomes": [
                                {"name": "New York Yankees", "price": -110, "point": -1.5},
                                {"name": "Boston Red Sox", "price": -110, "point": 1.5},
                            ],
                        },
                        {
                            "key": "totals",
                            "outcomes": [
                                {"name": "Over", "price": -110, "point": 8.5},
                                {"name": "Under", "price": -110, "point": 8.5},
                            ],
                        },
                    ],
                },
                {
                    "key": "fanduel",
                    "title": "FanDuel",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "New York Yankees", "price": -145},
                                {"name": "Boston Red Sox", "price": 125},
                            ],
                        }
                        # No spreads / totals from FanDuel in this snapshot
                    ],
                },
            ],
        }
    ]


# ─── parse_odds_response ─────────────────────────────────────────────────────


class TestParseOddsResponse:
    def test_flattens_two_books_into_two_rows(self, sample_response: list[dict]) -> None:
        rows = parse_odds_response(sample_response)
        assert len(rows) == 2

    def test_draftkings_row_has_all_markets(self, sample_response: list[dict]) -> None:
        rows = parse_odds_response(sample_response)
        dk = next(r for r in rows if r["sportsbook"] == "draftkings")
        assert dk["home_team"] == "New York Yankees"
        assert dk["away_team"] == "Boston Red Sox"
        assert dk["home_moneyline"] == -150
        assert dk["away_moneyline"] == 130
        assert dk["spread_home"] == -1.5
        assert dk["spread_away"] == 1.5
        assert dk["over_under"] == 8.5
        assert isinstance(dk["fetched_at"], datetime)

    def test_fanduel_row_has_only_moneylines(self, sample_response: list[dict]) -> None:
        rows = parse_odds_response(sample_response)
        fd = next(r for r in rows if r["sportsbook"] == "fanduel")
        assert fd["home_moneyline"] == -145
        assert fd["away_moneyline"] == 125
        assert fd["spread_home"] is None
        assert fd["spread_away"] is None
        assert fd["over_under"] is None

    def test_commence_time_parsed_to_datetime(self, sample_response: list[dict]) -> None:
        rows = parse_odds_response(sample_response)
        ct = rows[0]["commence_time"]
        assert ct.year == 2026 and ct.month == 5 and ct.day == 22
        assert ct.hour == 23 and ct.minute == 5

    def test_malformed_game_skipped(self) -> None:
        rows = parse_odds_response(
            [
                {"home_team": "A"},  # missing away_team + commence_time
                {
                    "home_team": "X",
                    "away_team": "Y",
                    "commence_time": "not-an-iso-date",
                    "bookmakers": [],
                },
            ]
        )
        assert rows == []

    def test_empty_response_returns_empty_list(self) -> None:
        assert parse_odds_response([]) == []


# ─── match_odds_to_games ─────────────────────────────────────────────────────


class TestMatchOddsToGames:
    async def test_matches_on_teams_and_date(self) -> None:
        async with TestSessionLocal() as session:
            session.add_all(
                [
                    Game(
                        mlb_game_id=8001,
                        date=_date(2026, 5, 22),
                        home_team="New York Yankees",
                        away_team="Boston Red Sox",
                        status="Scheduled",
                    ),
                    Game(
                        mlb_game_id=8002,
                        date=_date(2026, 5, 22),
                        home_team="Los Angeles Dodgers",
                        away_team="San Francisco Giants",
                        status="Scheduled",
                    ),
                ]
            )
            await session.commit()

        rows = parse_odds_response(
            [
                {
                    "home_team": "New York Yankees",
                    "away_team": "Boston Red Sox",
                    "commence_time": "2026-05-22T23:05:00Z",
                    "bookmakers": [
                        {
                            "key": "draftkings",
                            "markets": [
                                {
                                    "key": "h2h",
                                    "outcomes": [
                                        {"name": "New York Yankees", "price": -150},
                                        {"name": "Boston Red Sox", "price": 130},
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        )

        async with TestSessionLocal() as session:
            matched = await match_odds_to_games(session, rows)

        assert len(matched) == 1
        flat, game_id = matched[0]
        assert flat["sportsbook"] == "draftkings"
        assert isinstance(game_id, int) and game_id > 0

    async def test_unknown_team_is_skipped_not_raised(self) -> None:
        rows = parse_odds_response(
            [
                {
                    "home_team": "Phantom FC",
                    "away_team": "Ghost SC",
                    "commence_time": "2026-05-22T23:00:00Z",
                    "bookmakers": [],
                }
            ]
        )
        async with TestSessionLocal() as session:
            matched = await match_odds_to_games(session, rows)
        # No games seeded for that pair; matcher returns empty, no exception
        assert matched == []

    async def test_empty_input_returns_empty(self) -> None:
        async with TestSessionLocal() as session:
            assert await match_odds_to_games(session, []) == []


# ─── OddsClient (HTTP layer, fully mocked) ───────────────────────────────────


class TestOddsClient:
    @respx.mock
    async def test_get_todays_odds_happy_path(
        self, sample_response: list[dict]
    ) -> None:
        respx.get(BASE_URL).mock(
            return_value=httpx.Response(
                200,
                json=sample_response,
                headers={
                    "x-requests-remaining": "498",
                    "x-requests-used": "2",
                },
            )
        )
        async with OddsClient(api_key="fake-key") as oc:
            data = await oc.get_todays_odds()
            assert len(data) == 1
            assert await oc.get_remaining_quota() == 498
            assert oc.last_used_quota == 2

    @respx.mock
    async def test_quota_exhausted_raises(self) -> None:
        respx.get(BASE_URL).mock(
            return_value=httpx.Response(
                429,
                text="quota exhausted",
                headers={"x-requests-remaining": "0", "x-requests-used": "500"},
            )
        )
        async with OddsClient(api_key="fake-key") as oc:
            with pytest.raises(OddsQuotaExhausted):
                await oc.get_todays_odds()
            assert oc.last_remaining_quota == 0

    @respx.mock
    async def test_500_raises_odds_api_error(self) -> None:
        respx.get(BASE_URL).mock(
            return_value=httpx.Response(500, text="upstream error", headers={})
        )
        async with OddsClient(api_key="fake-key") as oc:
            with pytest.raises(OddsApiError):
                await oc.get_todays_odds()

    @respx.mock
    async def test_non_list_response_raises(self) -> None:
        respx.get(BASE_URL).mock(
            return_value=httpx.Response(
                200, json={"unexpected": "shape"}, headers={"x-requests-remaining": "499"}
            )
        )
        async with OddsClient(api_key="fake-key") as oc:
            with pytest.raises(OddsApiError, match="unexpected response shape"):
                await oc.get_todays_odds()

    async def test_missing_api_key_refuses(self) -> None:
        with pytest.raises(OddsApiError, match="requires an API key"):
            OddsClient(api_key=None)
        with pytest.raises(OddsApiError, match="requires an API key"):
            OddsClient(api_key="")
