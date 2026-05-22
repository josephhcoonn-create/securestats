"""
Task 3.4 — ETL Pipeline Tests
==============================

Test classes
────────────
TestMLBClientParsing   — respx mocks the real MLB HTTPS endpoint; verifies
                         that mlb_client.py parses raw JSON into typed dicts.
TestETLUpsertBehavior  — patches MLBClient so ETL runs against the test DB
                         without hitting the network; checks insert/update
                         counts and DB state directly.
TestETLErrorHandling   — verifies savepoint isolation: one failed game records
                         an error without crashing the pipeline, and a total
                         API failure surfaces as ETLResult.errors.
TestBackfillDateRange  — multi-day iteration and invalid-range ValueError.
TestETLTriggerEndpoint — exercises /etl/trigger HTTP endpoint and RBAC rules.
"""

import json
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import func, select

from app.models.batting_stats import BattingStats
from app.models.game import Game
from app.models.player import Player
from app.services.etl import (
    ETLResult,
    backfill_date_range,
    run_daily_etl,
    run_etl_for_date,
    run_live_update,
)
from app.services.mlb_client import BattingStatsInfo, GameInfo, MLBClient
from tests.conftest import TestSessionLocal

# ── Fixture file helpers ───────────────────────────────────────────────────────

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ── Canonical sample data (must match fixture JSON exactly) ───────────────────

GAME_ID = 823462
GAME_DATE = "2026-05-20"

SAMPLE_GAME: GameInfo = GameInfo(
    game_id=GAME_ID,
    date=GAME_DATE,
    home_team="Philadelphia Phillies",
    home_team_id=143,
    away_team="Cincinnati Reds",
    away_team_id=113,
    home_score=7,
    away_score=3,
    status="Final",
)

BATTER_TURNER: BattingStatsInfo = BattingStatsInfo(
    player_id=656756,
    player_name="Trea Turner",
    team="Philadelphia Phillies",
    team_id=143,
    position="SS",
    at_bats=4,
    hits=2,
    home_runs=1,
    rbis=2,
    batting_avg=0.289,
    on_base_pct=0.342,
    slugging_pct=0.512,
)

BATTER_HARPER: BattingStatsInfo = BattingStatsInfo(
    player_id=514888,
    player_name="Bryce Harper",
    team="Philadelphia Phillies",
    team_id=143,
    position="1B",
    at_bats=3,
    hits=1,
    home_runs=0,
    rbis=1,
    batting_avg=0.310,
    on_base_pct=0.400,
    slugging_pct=0.540,
)

BATTER_CRUZ: BattingStatsInfo = BattingStatsInfo(
    player_id=669742,
    player_name="Elly De La Cruz",
    team="Cincinnati Reds",
    team_id=113,
    position="SS",
    at_bats=4,
    hits=1,
    home_runs=1,
    rbis=3,
    batting_avg=0.245,
    on_base_pct=0.310,
    slugging_pct=0.480,
)

SAMPLE_BATTING_LINES = [BATTER_TURNER, BATTER_HARPER, BATTER_CRUZ]


# ── Mock MLBClient factory ─────────────────────────────────────────────────────


def _mock_mlb_cls(
    schedule: list[GameInfo] | None = None,
    boxscore: list[BattingStatsInfo] | None = None,
    boxscore_exc: Exception | None = None,
    schedule_exc: Exception | None = None,
) -> MagicMock:
    """
    Return a MagicMock that behaves like the MLBClient class when used as
    ``async with MLBClient() as mlb:``.

    ``schedule``     — what get_todays_schedule() returns (default: [SAMPLE_GAME])
    ``boxscore``     — what get_game_boxscore() returns  (default: SAMPLE_BATTING_LINES)
    ``boxscore_exc`` — if set, get_game_boxscore() raises this exception
    ``schedule_exc`` — if set, get_todays_schedule() raises this exception
    """
    instance = AsyncMock()
    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__ = AsyncMock(return_value=False)

    if schedule_exc:
        instance.get_todays_schedule = AsyncMock(side_effect=schedule_exc)
    else:
        instance.get_todays_schedule = AsyncMock(
            return_value=schedule if schedule is not None else [SAMPLE_GAME]
        )

    if boxscore_exc:
        instance.get_game_boxscore = AsyncMock(side_effect=boxscore_exc)
    else:
        instance.get_game_boxscore = AsyncMock(
            return_value=boxscore if boxscore is not None else SAMPLE_BATTING_LINES
        )

    return MagicMock(return_value=instance)


# ── Helper: build a minimal ETLResult ─────────────────────────────────────────


def _etl_ok(**overrides) -> ETLResult:
    """Return a successful ETLResult with sensible test defaults."""
    r = ETLResult(
        run_date=date(2026, 5, 20),
        games_processed=1,
        players_upserted=3,
        stats_inserted=3,
        stats_updated=0,
        duration_seconds=0.5,
    )
    for k, v in overrides.items():
        setattr(r, k, v)
    return r


# ══════════════════════════════════════════════════════════════════════════════
# 1. MLB API client parsing
# ══════════════════════════════════════════════════════════════════════════════


class TestMLBClientParsing:
    """
    Verify that MLBClient correctly parses raw MLB API JSON into typed dicts.
    respx intercepts the real httpx calls — no network traffic.
    """

    async def test_schedule_parsing(self):
        """get_todays_schedule returns correct GameInfo dicts from fixture JSON."""
        fixture = load_fixture("schedule_2026_05_20.json")

        with respx.mock(assert_all_called=False) as mock_router:
            mock_router.get("https://statsapi.mlb.com/api/v1/schedule").mock(
                return_value=httpx.Response(200, json=fixture)
            )
            async with MLBClient() as mlb:
                games = await mlb.get_todays_schedule(date(2026, 5, 20))

        assert len(games) == 2  # fixture has 1 Final + 1 Scheduled

        final = games[0]
        assert final["game_id"] == GAME_ID
        assert final["date"] == GAME_DATE
        assert final["home_team"] == "Philadelphia Phillies"
        assert final["home_team_id"] == 143
        assert final["away_team"] == "Cincinnati Reds"
        assert final["away_score"] == 3
        assert final["home_score"] == 7
        assert final["status"] == "Final"

        scheduled = games[1]
        assert scheduled["game_id"] == 823463
        assert scheduled["status"] == "Scheduled"
        assert scheduled["home_score"] is None  # Scheduled game has no score key

    async def test_boxscore_parsing(self):
        """get_game_boxscore returns correct BattingStatsInfo dicts from fixture JSON."""
        fixture = load_fixture("boxscore_823462.json")

        with respx.mock(assert_all_called=False) as mock_router:
            mock_router.get(
                f"https://statsapi.mlb.com/api/v1/game/{GAME_ID}/boxscore"
            ).mock(return_value=httpx.Response(200, json=fixture))
            async with MLBClient() as mlb:
                lines = await mlb.get_game_boxscore(GAME_ID)

        assert len(lines) == 3  # 2 home + 1 away

        turner = next(l for l in lines if l["player_id"] == 656756)
        assert turner["player_name"] == "Trea Turner"
        assert turner["team"] == "Philadelphia Phillies"
        assert turner["position"] == "SS"
        assert turner["at_bats"] == 4
        assert turner["hits"] == 2
        assert turner["home_runs"] == 1
        assert turner["rbis"] == 2
        assert turner["batting_avg"] == pytest.approx(0.289)
        assert turner["on_base_pct"] == pytest.approx(0.342)
        assert turner["slugging_pct"] == pytest.approx(0.512)

        cruz = next(l for l in lines if l["player_id"] == 669742)
        assert cruz["team"] == "Cincinnati Reds"
        assert cruz["position"] == "SS"


# ══════════════════════════════════════════════════════════════════════════════
# 2. ETL upsert behaviour
# ══════════════════════════════════════════════════════════════════════════════


class TestETLUpsertBehavior:
    """
    Run run_etl_for_date against the test DB with a mocked MLBClient and
    confirm the correct rows are created / updated.
    """

    async def test_new_records_are_inserted(self):
        """First ETL run inserts players, game, and batting-stat rows."""
        with patch("app.services.etl.MLBClient", _mock_mlb_cls()):
            result = await run_etl_for_date(date(2026, 5, 20))

        assert result.success
        assert result.games_processed == 1
        assert result.players_upserted == 3
        assert result.stats_inserted == 3
        assert result.stats_updated == 0

        async with TestSessionLocal() as session:
            player_count = (await session.execute(select(func.count(Player.id)))).scalar()
            game_count = (await session.execute(select(func.count(Game.id)))).scalar()
            stat_count = (await session.execute(select(func.count(BattingStats.id)))).scalar()

        assert player_count == 3
        assert game_count == 1
        assert stat_count == 3

    async def test_player_upsert_no_duplicate(self):
        """Running ETL twice for the same game does NOT create duplicate player rows."""
        mock_cls = _mock_mlb_cls()
        with patch("app.services.etl.MLBClient", mock_cls):
            await run_etl_for_date(date(2026, 5, 20))
            await run_etl_for_date(date(2026, 5, 20))

        async with TestSessionLocal() as session:
            player_count = (await session.execute(select(func.count(Player.id)))).scalar()

        assert player_count == 3  # still exactly 3, no duplicates

    async def test_batting_stats_updated_on_rerun(self):
        """Second ETL run updates stats rows rather than inserting new ones."""
        updated_lines = [
            BattingStatsInfo(**{**BATTER_TURNER, "hits": 3, "rbis": 4}),
            BATTER_HARPER,
            BATTER_CRUZ,
        ]

        with patch("app.services.etl.MLBClient", _mock_mlb_cls()):
            await run_etl_for_date(date(2026, 5, 20))

        with patch("app.services.etl.MLBClient", _mock_mlb_cls(boxscore=updated_lines)):
            result = await run_etl_for_date(date(2026, 5, 20))

        assert result.stats_inserted == 0
        assert result.stats_updated == 3

        # Confirm the updated values are persisted
        async with TestSessionLocal() as session:
            turner_player = (
                await session.execute(
                    select(Player).where(Player.mlb_id == 656756)
                )
            ).scalar_one()
            stats_row = (
                await session.execute(
                    select(BattingStats).where(BattingStats.player_id == turner_player.id)
                )
            ).scalar_one()

        assert stats_row.hits == 3
        assert stats_row.rbis == 4

    async def test_game_score_updated_on_rerun(self):
        """A second ETL run refreshes home/away scores on the Game row."""
        # First run: score 7-3
        with patch("app.services.etl.MLBClient", _mock_mlb_cls()):
            await run_etl_for_date(date(2026, 5, 20))

        # Second run: score now 9-3 (e.g., extra innings finished)
        updated_game = GameInfo(**{**SAMPLE_GAME, "home_score": 9})
        with patch(
            "app.services.etl.MLBClient",
            _mock_mlb_cls(schedule=[updated_game]),
        ):
            await run_etl_for_date(date(2026, 5, 20))

        async with TestSessionLocal() as session:
            game_count = (await session.execute(select(func.count(Game.id)))).scalar()
            game = (
                await session.execute(select(Game).where(Game.mlb_game_id == GAME_ID))
            ).scalar_one()

        assert game_count == 1  # no duplicate
        assert game.home_score == 9


# ══════════════════════════════════════════════════════════════════════════════
# 3. Error-handling / pipeline resilience
# ══════════════════════════════════════════════════════════════════════════════


class TestETLErrorHandling:
    """
    Verify that individual failures are isolated and the pipeline keeps running.
    """

    async def test_boxscore_failure_recorded_in_errors(self):
        """
        When get_game_boxscore raises, the game's error is appended to
        ETLResult.errors but the pipeline does not crash and still returns.
        """
        mock_cls = _mock_mlb_cls(boxscore_exc=RuntimeError("boxscore unavailable"))

        with patch("app.services.etl.MLBClient", mock_cls):
            result = await run_etl_for_date(date(2026, 5, 20))

        assert not result.success
        assert len(result.errors) >= 1
        assert any("823462" in err for err in result.errors)
        # The game row IS upserted before the boxscore fetch fails
        assert result.games_processed == 0  # _process_game never completes

    async def test_schedule_api_failure_returns_error_result(self):
        """
        A complete API failure (schedule fetch raises) surfaces as an
        ETLResult with errors and does not propagate an exception.
        """
        mock_cls = _mock_mlb_cls(schedule_exc=RuntimeError("MLB API is down"))

        with patch("app.services.etl.MLBClient", mock_cls):
            result = await run_etl_for_date(date(2026, 5, 20))

        assert not result.success
        assert len(result.errors) >= 1
        assert result.games_processed == 0

    async def test_no_processable_games_returns_empty_success(self):
        """
        A schedule with only Scheduled games (none in PROCESSABLE_STATUSES)
        returns a successful result with zero games processed.
        """
        scheduled_only = [GameInfo(**{**SAMPLE_GAME, "status": "Scheduled"})]
        mock_cls = _mock_mlb_cls(schedule=scheduled_only)

        with patch("app.services.etl.MLBClient", mock_cls):
            result = await run_etl_for_date(date(2026, 5, 20))

        assert result.success
        assert result.games_processed == 0
        assert result.stats_inserted == 0


# ══════════════════════════════════════════════════════════════════════════════
# 4. backfill_date_range
# ══════════════════════════════════════════════════════════════════════════════


class TestBackfillDateRange:
    async def test_processes_each_day_in_range(self):
        """backfill_date_range calls run_etl_for_date once per calendar day."""
        start = date(2026, 5, 18)
        end = date(2026, 5, 20)

        with patch(
            "app.services.etl.run_etl_for_date", new_callable=AsyncMock
        ) as mock_run:
            mock_run.side_effect = lambda d: ETLResult(run_date=d)
            results = await backfill_date_range(start, end)

        assert mock_run.call_count == 3
        assert len(results) == 3
        dates_called = [call.args[0] for call in mock_run.call_args_list]
        assert dates_called == [date(2026, 5, 18), date(2026, 5, 19), date(2026, 5, 20)]

    async def test_single_day_range(self):
        """start_date == end_date processes exactly one day."""
        target = date(2026, 5, 20)
        with patch(
            "app.services.etl.run_etl_for_date", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = ETLResult(run_date=target)
            results = await backfill_date_range(target, target)

        assert mock_run.call_count == 1
        assert len(results) == 1

    async def test_invalid_range_raises_value_error(self):
        """start_date > end_date raises ValueError immediately."""
        with pytest.raises(ValueError, match="must be"):
            await backfill_date_range(date(2026, 5, 20), date(2026, 5, 18))


# ══════════════════════════════════════════════════════════════════════════════
# 5. /etl/trigger HTTP endpoint — RBAC and response shape
# ══════════════════════════════════════════════════════════════════════════════


class TestETLTriggerEndpoint:
    """
    These tests exercise the FastAPI endpoint layer only.
    The ETL service functions are mocked so no DB or network calls are needed.
    """

    async def test_no_token_returns_403(self, client: AsyncClient):
        resp = await client.post("/api/v1/etl/trigger")
        assert resp.status_code == 403

    async def test_viewer_returns_403(
        self, client: AsyncClient, viewer_headers: dict
    ):
        resp = await client.post("/api/v1/etl/trigger", headers=viewer_headers)
        assert resp.status_code == 403

    async def test_analyst_returns_403(
        self, client: AsyncClient, analyst_headers: dict
    ):
        resp = await client.post("/api/v1/etl/trigger", headers=analyst_headers)
        assert resp.status_code == 403

    async def test_admin_triggers_full_etl(
        self, client: AsyncClient, admin_headers: dict
    ):
        """Admin with live_only=false (default) calls run_daily_etl."""
        mock_result = _etl_ok()

        with patch("app.api.etl.run_daily_etl", new_callable=AsyncMock) as mock_etl:
            mock_etl.return_value = mock_result
            resp = await client.post(
                "/api/v1/etl/trigger", headers=admin_headers
            )

        assert resp.status_code == 200
        mock_etl.assert_called_once()

        body = resp.json()
        assert body["status"] == "success"
        assert body["success"] is True
        assert body["games_processed"] == 1
        assert body["players_upserted"] == 3
        assert body["stats_inserted"] == 3
        assert body["stats_updated"] == 0
        assert body["errors"] == []
        assert body["duration_seconds"] == pytest.approx(0.5)

    async def test_admin_triggers_live_update(
        self, client: AsyncClient, admin_headers: dict
    ):
        """Admin with live_only=true calls run_live_update instead."""
        mock_result = _etl_ok(stats_inserted=0, stats_updated=2)

        with patch("app.api.etl.run_live_update", new_callable=AsyncMock) as mock_live:
            mock_live.return_value = mock_result
            resp = await client.post(
                "/api/v1/etl/trigger?live_only=true", headers=admin_headers
            )

        assert resp.status_code == 200
        mock_live.assert_called_once()

        body = resp.json()
        assert body["stats_updated"] == 2
        assert body["stats_inserted"] == 0

    async def test_partial_failure_status(
        self, client: AsyncClient, admin_headers: dict
    ):
        """When ETLResult.errors is non-empty, status field is 'partial_failure'."""
        mock_result = _etl_ok(
            errors=["game 823462 player 656756: some db error"],
            stats_inserted=2,
        )

        with patch("app.api.etl.run_daily_etl", new_callable=AsyncMock) as mock_etl:
            mock_etl.return_value = mock_result
            resp = await client.post(
                "/api/v1/etl/trigger", headers=admin_headers
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "partial_failure"
        assert body["success"] is False
        assert len(body["errors"]) == 1
