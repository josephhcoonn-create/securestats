"""
Task 4.2 — Analytics endpoint tests.

Strategy
────────
Seed realistic data directly via TestSessionLocal for each test class,
then hit the HTTP endpoints.  Tests verify:
  • correct analytic logic (rankings, averages, streaks)
  • RBAC (analyst required; viewer blocked)
  • edge-cases (empty DB, single player, player not found)

TestRBAC                 — all endpoints require analyst role
TestBattingLeaders       — ranking order, stat variants, days filter
TestTeamRankings         — team aggregation and order
TestHitProbability       — formula math, 404, zero-data fallback
TestHotColdStreaks        — hot / cold detection, min_games window
TestPlayerComparison     — side-by-side stats, leaders dict, missing player
"""

import math
from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from app.models.batting_stats import BattingStats
from app.models.game import Game
from app.models.player import Player
from tests.conftest import TestSessionLocal


# ── Seed helpers ──────────────────────────────────────────────────────────────


async def _player(
    mlb_id: int,
    full_name: str = "Player",
    team: str = "Team A",
    position: str = "OF",
) -> Player:
    async with TestSessionLocal() as s:
        p = Player(mlb_id=mlb_id, full_name=full_name, team=team, position=position)
        s.add(p)
        await s.commit()
        await s.refresh(p)
        return p


async def _game(
    mlb_game_id: int,
    game_date: date | None = None,
    status: str = "Final",
    home_team: str = "Team A",
    away_team: str = "Team B",
) -> Game:
    async with TestSessionLocal() as s:
        g = Game(
            mlb_game_id=mlb_game_id,
            date=game_date or date(2026, 5, 20),
            home_team=home_team,
            away_team=away_team,
            home_score=5,
            away_score=3,
            status=status,
        )
        s.add(g)
        await s.commit()
        await s.refresh(g)
        return g


async def _stat(
    player: Player,
    game: Game,
    *,
    at_bats: int = 4,
    hits: int = 1,
    home_runs: int = 0,
    rbis: int = 0,
    batting_avg: float = 0.250,
    on_base_pct: float = 0.320,
    slugging_pct: float = 0.400,
) -> BattingStats:
    async with TestSessionLocal() as s:
        bs = BattingStats(
            player_id=player.id,
            game_id=game.id,
            at_bats=at_bats,
            hits=hits,
            home_runs=home_runs,
            rbis=rbis,
            batting_avg=batting_avg,
            on_base_pct=on_base_pct,
            slugging_pct=slugging_pct,
        )
        s.add(bs)
        await s.commit()
        await s.refresh(bs)
        return bs


# ══════════════════════════════════════════════════════════════════════════════
# RBAC — all endpoints require analyst or above
# ══════════════════════════════════════════════════════════════════════════════


class TestRBAC:
    ENDPOINTS = [
        ("GET", "/api/v1/stats/leaders"),
        ("GET", "/api/v1/stats/teams"),
        ("GET", "/api/v1/stats/streaks"),
    ]

    async def test_unauthenticated_blocked(self, client: AsyncClient):
        for method, path in self.ENDPOINTS:
            resp = await client.request(method, path)
            assert resp.status_code == 403, f"{path} should block unauthenticated"

    async def test_viewer_blocked(self, client: AsyncClient, viewer_headers: dict):
        for method, path in self.ENDPOINTS:
            resp = await client.request(method, path, headers=viewer_headers)
            assert resp.status_code == 403, f"{path} should block viewer"

    async def test_analyst_allowed(self, client: AsyncClient, analyst_headers: dict):
        for method, path in self.ENDPOINTS:
            resp = await client.request(method, path, headers=analyst_headers)
            assert resp.status_code == 200, f"{path} should allow analyst"

    async def test_hit_probability_viewer_blocked(
        self, client: AsyncClient, viewer_headers: dict
    ):
        resp = await client.get(
            "/api/v1/stats/hit-probability/1", headers=viewer_headers
        )
        assert resp.status_code == 403

    async def test_compare_viewer_blocked(
        self, client: AsyncClient, viewer_headers: dict
    ):
        resp = await client.post(
            "/api/v1/stats/compare",
            json={"player_ids": [1, 2]},
            headers=viewer_headers,
        )
        assert resp.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
# Batting leaders
# ══════════════════════════════════════════════════════════════════════════════


class TestBattingLeaders:
    async def test_empty_db_returns_empty_list(
        self, client: AsyncClient, analyst_headers: dict
    ):
        resp = await client.get("/api/v1/stats/leaders", headers=analyst_headers)
        assert resp.status_code == 200
        assert resp.json()["leaders"] == []

    async def test_ranking_order_batting_avg(
        self, client: AsyncClient, analyst_headers: dict
    ):
        """Player with higher batting average ranks first."""
        p_high = await _player(mlb_id=1, full_name="High Avg")
        p_low = await _player(mlb_id=2, full_name="Low Avg")
        g = await _game(mlb_game_id=1000)

        # p_high: 8 hits / 10 AB = .800 (unrealistic but clear)
        await _stat(p_high, g, at_bats=10, hits=8, batting_avg=0.800)
        # p_low: 1 hit / 10 AB = .100
        await _stat(p_low, g, at_bats=10, hits=1, batting_avg=0.100)

        resp = await client.get(
            "/api/v1/stats/leaders?stat=batting_avg", headers=analyst_headers
        )
        leaders = resp.json()["leaders"]
        assert len(leaders) == 2
        assert leaders[0]["full_name"] == "High Avg"
        assert leaders[0]["rank"] == 1
        assert leaders[1]["full_name"] == "Low Avg"
        assert leaders[1]["rank"] == 2

    async def test_ranking_order_home_runs(
        self, client: AsyncClient, analyst_headers: dict
    ):
        p1 = await _player(mlb_id=10, full_name="Slugger")
        p2 = await _player(mlb_id=11, full_name="Singles")
        g = await _game(mlb_game_id=1001)

        await _stat(p1, g, at_bats=10, hits=3, home_runs=5)
        await _stat(p2, g, at_bats=10, hits=4, home_runs=1)

        resp = await client.get(
            "/api/v1/stats/leaders?stat=home_runs", headers=analyst_headers
        )
        leaders = resp.json()["leaders"]
        assert leaders[0]["full_name"] == "Slugger"
        assert leaders[0]["value"] == 5

    async def test_limit_respected(self, client: AsyncClient, analyst_headers: dict):
        g = await _game(mlb_game_id=1002)
        for i in range(5):
            p = await _player(mlb_id=20 + i, full_name=f"P{i}")
            await _stat(p, g, at_bats=10, hits=i + 1)

        resp = await client.get(
            "/api/v1/stats/leaders?limit=3", headers=analyst_headers
        )
        assert len(resp.json()["leaders"]) == 3

    async def test_min_ab_qualifier_excludes_small_samples(
        self, client: AsyncClient, analyst_headers: dict
    ):
        """Players with < 10 AB do not appear in leaders."""
        p_few = await _player(mlb_id=30, full_name="Few AB")
        g = await _game(mlb_game_id=1003)
        # Only 3 at-bats — below the 10 AB minimum
        await _stat(p_few, g, at_bats=3, hits=3)

        resp = await client.get("/api/v1/stats/leaders", headers=analyst_headers)
        assert resp.json()["leaders"] == []

    async def test_days_filter_excludes_old_games(
        self, client: AsyncClient, analyst_headers: dict
    ):
        """Games outside the rolling window don't count."""
        p = await _player(mlb_id=40, full_name="Old Results")
        old_game = await _game(
            mlb_game_id=1004,
            game_date=date.today() - timedelta(days=60),
        )
        await _stat(p, old_game, at_bats=20, hits=10)

        # Query last 30 days → player's stats are excluded
        resp = await client.get(
            "/api/v1/stats/leaders?days=30", headers=analyst_headers
        )
        assert resp.json()["leaders"] == []

    async def test_invalid_stat_returns_422(
        self, client: AsyncClient, analyst_headers: dict
    ):
        resp = await client.get(
            "/api/v1/stats/leaders?stat=nonsense", headers=analyst_headers
        )
        assert resp.status_code == 422

    async def test_display_value_format_avg(
        self, client: AsyncClient, analyst_headers: dict
    ):
        """batting_avg display value should use '.NNN' format."""
        p = await _player(mlb_id=50, full_name="Display Test")
        g = await _game(mlb_game_id=1005)
        await _stat(p, g, at_bats=10, hits=3)  # .300

        resp = await client.get(
            "/api/v1/stats/leaders?stat=batting_avg", headers=analyst_headers
        )
        leader = resp.json()["leaders"][0]
        assert leader["display_value"] == ".300"
        assert leader["value"] == pytest.approx(0.3)

    async def test_display_value_format_hr(
        self, client: AsyncClient, analyst_headers: dict
    ):
        """home_runs display value should be a plain integer string."""
        p = await _player(mlb_id=51, full_name="HR Display")
        g = await _game(mlb_game_id=1006)
        await _stat(p, g, at_bats=10, hits=3, home_runs=7)

        resp = await client.get(
            "/api/v1/stats/leaders?stat=home_runs", headers=analyst_headers
        )
        assert resp.json()["leaders"][0]["display_value"] == "7"


# ══════════════════════════════════════════════════════════════════════════════
# Team rankings
# ══════════════════════════════════════════════════════════════════════════════


class TestTeamRankings:
    async def test_empty_db(self, client: AsyncClient, analyst_headers: dict):
        resp = await client.get("/api/v1/stats/teams", headers=analyst_headers)
        assert resp.status_code == 200
        assert resp.json()["rankings"] == []

    async def test_team_order_by_home_runs(
        self, client: AsyncClient, analyst_headers: dict
    ):
        g = await _game(mlb_game_id=2000)

        # Team A: 3 players × 5 HR = 15 HR total
        for i in range(3):
            p = await _player(mlb_id=60 + i, team="Team A", position="OF")
            await _stat(p, g, at_bats=20, hits=5, home_runs=5)

        # Team B: 3 players × 2 HR = 6 HR total
        for i in range(3):
            p = await _player(mlb_id=70 + i, team="Team B", position="OF")
            await _stat(p, g, at_bats=20, hits=4, home_runs=2)

        resp = await client.get(
            "/api/v1/stats/teams?stat=home_runs", headers=analyst_headers
        )
        rankings = resp.json()["rankings"]
        assert rankings[0]["team"] == "Team A"
        assert rankings[0]["rank"] == 1
        assert rankings[1]["team"] == "Team B"

    async def test_team_batting_avg(self, client: AsyncClient, analyst_headers: dict):
        g = await _game(mlb_game_id=2001)

        # High-avg team: 60 hits / 100 AB = .600
        for i in range(5):
            p = await _player(mlb_id=80 + i, team="High Team", position="OF")
            await _stat(p, g, at_bats=20, hits=12)

        # Low-avg team: 20 hits / 100 AB = .200
        for i in range(5):
            p = await _player(mlb_id=90 + i, team="Low Team", position="OF")
            await _stat(p, g, at_bats=20, hits=4)

        resp = await client.get(
            "/api/v1/stats/teams?stat=batting_avg", headers=analyst_headers
        )
        rankings = resp.json()["rankings"]
        assert rankings[0]["team"] == "High Team"

    async def test_team_min_ab_qualifier(
        self, client: AsyncClient, analyst_headers: dict
    ):
        """Teams with < 50 AB don't appear in rankings."""
        g = await _game(mlb_game_id=2002)
        p = await _player(mlb_id=100, team="Tiny Team", position="OF")
        # Only 10 AB — below 50 AB team minimum
        await _stat(p, g, at_bats=10, hits=5)

        resp = await client.get(
            "/api/v1/stats/teams?stat=batting_avg", headers=analyst_headers
        )
        assert resp.json()["rankings"] == []


# ══════════════════════════════════════════════════════════════════════════════
# Hit probability
# ══════════════════════════════════════════════════════════════════════════════


class TestHitProbability:
    async def test_player_not_found_404(
        self, client: AsyncClient, analyst_headers: dict
    ):
        resp = await client.get(
            "/api/v1/stats/hit-probability/999999", headers=analyst_headers
        )
        assert resp.status_code == 404

    async def test_probability_in_valid_range(
        self, client: AsyncClient, analyst_headers: dict
    ):
        p = await _player(mlb_id=200, full_name="Prob Player")
        g = await _game(
            mlb_game_id=3000,
            game_date=date.today() - timedelta(days=5),
        )
        await _stat(p, g, at_bats=10, hits=3)

        resp = await client.get(
            f"/api/v1/stats/hit-probability/{p.id}", headers=analyst_headers
        )
        assert resp.status_code == 200
        body = resp.json()
        prob = body["hit_probability"]
        assert 0.0 <= prob <= 1.0

    async def test_formula_weights(self, client: AsyncClient, analyst_headers: dict):
        """
        With only recent data, probability ≈ 0.5*recent + 0.3*career + 0.2*league.
        Recent and career are the same when there's only one game.
        """
        p = await _player(mlb_id=201, full_name="Formula Player")
        g = await _game(
            mlb_game_id=3001,
            game_date=date.today() - timedelta(days=5),
        )
        # 5 hits / 10 AB = .500 batting average
        await _stat(p, g, at_bats=10, hits=5)

        resp = await client.get(
            f"/api/v1/stats/hit-probability/{p.id}", headers=analyst_headers
        )
        body = resp.json()
        # recent_avg = career_avg = .500 (single game)
        # league_avg = .500 (only player in DB)
        # probability = 0.5*0.5 + 0.3*0.5 + 0.2*0.5 = 0.5
        assert body["hit_probability"] == pytest.approx(0.5, abs=0.01)

    async def test_ci_bounds_valid(self, client: AsyncClient, analyst_headers: dict):
        p = await _player(mlb_id=202, full_name="CI Player")
        g = await _game(
            mlb_game_id=3002,
            game_date=date.today() - timedelta(days=3),
        )
        await _stat(p, g, at_bats=20, hits=6)

        resp = await client.get(
            f"/api/v1/stats/hit-probability/{p.id}", headers=analyst_headers
        )
        body = resp.json()
        assert body["ci_lower"] >= 0.0
        assert body["ci_upper"] <= 1.0
        assert body["ci_lower"] <= body["hit_probability"] <= body["ci_upper"]

    async def test_display_probability_format(
        self, client: AsyncClient, analyst_headers: dict
    ):
        p = await _player(mlb_id=203, full_name="Display Prob")
        g = await _game(
            mlb_game_id=3003,
            game_date=date.today() - timedelta(days=2),
        )
        await _stat(p, g, at_bats=10, hits=3)

        resp = await client.get(
            f"/api/v1/stats/hit-probability/{p.id}", headers=analyst_headers
        )
        body = resp.json()
        assert body["display_probability"].endswith("%")
        assert body["display_ci"].startswith("[") and body["display_ci"].endswith("]")

    async def test_confidence_low_when_few_ab(
        self, client: AsyncClient, analyst_headers: dict
    ):
        """< 15 recent AB → confidence = 'low'."""
        p = await _player(mlb_id=204, full_name="Low Conf")
        g = await _game(
            mlb_game_id=3004,
            game_date=date.today() - timedelta(days=1),
        )
        await _stat(p, g, at_bats=5, hits=2)

        resp = await client.get(
            f"/api/v1/stats/hit-probability/{p.id}", headers=analyst_headers
        )
        assert resp.json()["confidence"] == "low"

    async def test_confidence_high_when_many_ab(
        self, client: AsyncClient, analyst_headers: dict
    ):
        """≥ 50 recent AB → confidence = 'high'."""
        p = await _player(mlb_id=205, full_name="High Conf")
        # Spread over multiple recent games to accumulate 60 AB
        for i in range(6):
            g = await _game(
                mlb_game_id=3010 + i,
                game_date=date.today() - timedelta(days=i + 1),
            )
            await _stat(p, g, at_bats=10, hits=3)

        resp = await client.get(
            f"/api/v1/stats/hit-probability/{p.id}", headers=analyst_headers
        )
        assert resp.json()["confidence"] == "high"

    async def test_no_recent_data_falls_back_to_career(
        self, client: AsyncClient, analyst_headers: dict
    ):
        """Player with only old data (> 30 days ago) still gets a probability."""
        p = await _player(mlb_id=206, full_name="Old Data")
        g = await _game(
            mlb_game_id=3020,
            game_date=date.today() - timedelta(days=60),  # outside 30-day window
        )
        await _stat(p, g, at_bats=10, hits=3)

        resp = await client.get(
            f"/api/v1/stats/hit-probability/{p.id}", headers=analyst_headers
        )
        body = resp.json()
        assert resp.status_code == 200
        assert 0.0 <= body["hit_probability"] <= 1.0
        assert body["recent_avg"] is None  # no recent games
        assert body["career_avg"] is not None


# ══════════════════════════════════════════════════════════════════════════════
# Hot / cold streaks
# ══════════════════════════════════════════════════════════════════════════════


class TestHotColdStreaks:
    async def test_empty_db(self, client: AsyncClient, analyst_headers: dict):
        resp = await client.get("/api/v1/stats/streaks", headers=analyst_headers)
        assert resp.status_code == 200
        assert resp.json()["streaks"] == []

    async def test_hot_player_detected(self, client: AsyncClient, analyst_headers: dict):
        """Player with 5 games and avg >= .350 → streaks list includes them as 'hot'."""
        p = await _player(mlb_id=300, full_name="Hot Hitter")
        for i in range(5):
            g = await _game(
                mlb_game_id=4000 + i,
                game_date=date(2026, 5, 20) - timedelta(days=i),
            )
            # 2 hits / 4 AB = .500 per game → hot
            await _stat(p, g, at_bats=4, hits=2)

        resp = await client.get(
            "/api/v1/stats/streaks?type=hot&min_games=5", headers=analyst_headers
        )
        streaks = resp.json()["streaks"]
        assert len(streaks) == 1
        assert streaks[0]["full_name"] == "Hot Hitter"
        assert streaks[0]["streak_type"] == "hot"
        assert streaks[0]["period_avg"] == pytest.approx(0.5, abs=0.001)

    async def test_cold_player_detected(
        self, client: AsyncClient, analyst_headers: dict
    ):
        """Player with 5 games and avg <= .150 → classified as 'cold'."""
        p = await _player(mlb_id=301, full_name="Cold Hitter")
        for i in range(5):
            g = await _game(
                mlb_game_id=4010 + i,
                game_date=date(2026, 5, 20) - timedelta(days=i),
            )
            # 0 hits / 4 AB = .000 per game → cold
            await _stat(p, g, at_bats=4, hits=0)

        resp = await client.get(
            "/api/v1/stats/streaks?type=cold&min_games=5", headers=analyst_headers
        )
        streaks = resp.json()["streaks"]
        assert len(streaks) == 1
        assert streaks[0]["streak_type"] == "cold"

    async def test_average_player_excluded_from_both(
        self, client: AsyncClient, analyst_headers: dict
    ):
        """Player with avg between .150 and .350 doesn't appear in 'both'."""
        p = await _player(mlb_id=302, full_name="Average Joe")
        for i in range(5):
            g = await _game(
                mlb_game_id=4020 + i,
                game_date=date(2026, 5, 20) - timedelta(days=i),
            )
            # 1 hit / 4 AB = .250 → neither hot nor cold
            await _stat(p, g, at_bats=4, hits=1)

        resp = await client.get(
            "/api/v1/stats/streaks?type=both&min_games=5", headers=analyst_headers
        )
        assert resp.json()["streaks"] == []

    async def test_type_filter_hot_only(self, client: AsyncClient, analyst_headers: dict):
        """type=hot excludes cold players."""
        hot_p = await _player(mlb_id=310, full_name="Hot Only")
        cold_p = await _player(mlb_id=311, full_name="Cold Only")

        for i in range(5):
            g_hot = await _game(mlb_game_id=4030 + i, game_date=date(2026, 5, 10) - timedelta(days=i))
            g_cold = await _game(mlb_game_id=4040 + i, game_date=date(2026, 5, 15) - timedelta(days=i))
            await _stat(hot_p, g_hot, at_bats=4, hits=2)  # .500 hot
            await _stat(cold_p, g_cold, at_bats=4, hits=0)  # .000 cold

        resp = await client.get(
            "/api/v1/stats/streaks?type=hot&min_games=5", headers=analyst_headers
        )
        names = [s["full_name"] for s in resp.json()["streaks"]]
        assert "Hot Only" in names
        assert "Cold Only" not in names

    async def test_min_games_window_respected(
        self, client: AsyncClient, analyst_headers: dict
    ):
        """Player with only 3 final games is excluded when min_games=5."""
        p = await _player(mlb_id=320, full_name="Too Few Games")
        for i in range(3):
            g = await _game(
                mlb_game_id=4050 + i,
                game_date=date(2026, 5, 20) - timedelta(days=i),
            )
            await _stat(p, g, at_bats=4, hits=2)

        resp = await client.get(
            "/api/v1/stats/streaks?min_games=5", headers=analyst_headers
        )
        assert resp.json()["streaks"] == []

    async def test_only_final_games_count(
        self, client: AsyncClient, analyst_headers: dict
    ):
        """In-progress / scheduled games don't count toward streaks."""
        p = await _player(mlb_id=330, full_name="Scheduled Games")
        for i in range(5):
            g = await _game(
                mlb_game_id=4060 + i,
                game_date=date(2026, 5, 20) - timedelta(days=i),
                status="Scheduled",  # not Final
            )
            await _stat(p, g, at_bats=4, hits=2)

        resp = await client.get("/api/v1/stats/streaks", headers=analyst_headers)
        assert resp.json()["streaks"] == []


# ══════════════════════════════════════════════════════════════════════════════
# Player comparison
# ══════════════════════════════════════════════════════════════════════════════


class TestPlayerComparison:
    async def test_missing_player_returns_404(
        self, client: AsyncClient, analyst_headers: dict
    ):
        p = await _player(mlb_id=400, full_name="Real Player")
        resp = await client.post(
            "/api/v1/stats/compare",
            json={"player_ids": [p.id, 999999]},
            headers=analyst_headers,
        )
        assert resp.status_code == 404

    async def test_requires_at_least_two_players(
        self, client: AsyncClient, analyst_headers: dict
    ):
        p = await _player(mlb_id=401)
        resp = await client.post(
            "/api/v1/stats/compare",
            json={"player_ids": [p.id]},
            headers=analyst_headers,
        )
        assert resp.status_code == 422

    async def test_comparison_returns_all_players(
        self, client: AsyncClient, analyst_headers: dict
    ):
        p1 = await _player(mlb_id=410, full_name="Alpha")
        p2 = await _player(mlb_id=411, full_name="Beta")
        p3 = await _player(mlb_id=412, full_name="Gamma")

        resp = await client.post(
            "/api/v1/stats/compare",
            json={"player_ids": [p1.id, p2.id, p3.id]},
            headers=analyst_headers,
        )
        assert resp.status_code == 200
        players = resp.json()["players"]
        assert len(players) == 3
        names = {p["full_name"] for p in players}
        assert names == {"Alpha", "Beta", "Gamma"}

    async def test_leaders_dict_identifies_correct_player(
        self, client: AsyncClient, analyst_headers: dict
    ):
        p_slugger = await _player(mlb_id=420, full_name="Slugger")
        p_contact = await _player(mlb_id=421, full_name="Contact")
        g = await _game(mlb_game_id=5000)

        await _stat(p_slugger, g, at_bats=10, hits=2, home_runs=5, rbis=8)
        await _stat(p_contact, g, at_bats=10, hits=8, home_runs=0, rbis=2)

        resp = await client.post(
            "/api/v1/stats/compare",
            json={"player_ids": [p_slugger.id, p_contact.id]},
            headers=analyst_headers,
        )
        body = resp.json()
        leaders = body["leaders"]

        # Slugger leads in home_runs and rbis
        assert leaders["home_runs"] == p_slugger.id
        assert leaders["rbis"] == p_slugger.id
        # Contact player leads in batting_avg and hits
        assert leaders["batting_avg"] == p_contact.id
        assert leaders["hits"] == p_contact.id

    async def test_career_stats_are_aggregated_across_games(
        self, client: AsyncClient, analyst_headers: dict
    ):
        p1 = await _player(mlb_id=430, full_name="Multi Game")
        p2 = await _player(mlb_id=431, full_name="Single Game")

        g1 = await _game(mlb_game_id=5001, game_date=date(2026, 5, 19))
        g2 = await _game(mlb_game_id=5002, game_date=date(2026, 5, 20))

        await _stat(p1, g1, at_bats=4, hits=2, home_runs=1)
        await _stat(p1, g2, at_bats=4, hits=1, home_runs=2)
        await _stat(p2, g1, at_bats=4, hits=1, home_runs=0)

        resp = await client.post(
            "/api/v1/stats/compare",
            json={"player_ids": [p1.id, p2.id]},
            headers=analyst_headers,
        )
        players_map = {p["player_id"]: p for p in resp.json()["players"]}

        multi = players_map[p1.id]
        assert multi["games_played"] == 2
        assert multi["at_bats"] == 8
        assert multi["hits"] == 3
        assert multi["home_runs"] == 3

    async def test_display_values_present(
        self, client: AsyncClient, analyst_headers: dict
    ):
        p1 = await _player(mlb_id=440, full_name="Disp1")
        p2 = await _player(mlb_id=441, full_name="Disp2")
        g = await _game(mlb_game_id=5003)
        await _stat(p1, g, at_bats=10, hits=3, on_base_pct=0.350, slugging_pct=0.450)
        await _stat(p2, g, at_bats=10, hits=2)

        resp = await client.post(
            "/api/v1/stats/compare",
            json={"player_ids": [p1.id, p2.id]},
            headers=analyst_headers,
        )
        for p in resp.json()["players"]:
            assert "display_avg" in p
            assert "display_ops" in p
            assert "display_recent_avg" in p
