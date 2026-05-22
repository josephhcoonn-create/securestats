"""
Task 4.1 — Player & Game endpoint tests.

Strategy
────────
All tests run against the test database (same setup as test_auth.py /
test_etl.py).  Seed data is inserted directly via TestSessionLocal so tests
are independent of the ETL pipeline.

TestPlayerEndpoints   — CRUD + pagination + filtering + RBAC for /players
TestGameEndpoints     — CRUD + pagination + filtering + RBAC for /games
TestIntegration       — cross-resource: player stats endpoint returns game data
"""

from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.batting_stats import BattingStats
from app.models.game import Game
from app.models.player import Player
from tests.conftest import TestSessionLocal

# ── Seed helpers ──────────────────────────────────────────────────────────────


async def _seed_player(
    *,
    mlb_id: int = 656756,
    full_name: str = "Trea Turner",
    team: str = "Philadelphia Phillies",
    position: str = "SS",
) -> Player:
    async with TestSessionLocal() as session:
        p = Player(mlb_id=mlb_id, full_name=full_name, team=team, position=position)
        session.add(p)
        await session.commit()
        await session.refresh(p)
        return p


async def _seed_game(
    *,
    mlb_game_id: int = 823462,
    game_date: date | None = None,
    home_team: str = "Philadelphia Phillies",
    away_team: str = "Cincinnati Reds",
    home_score: int = 7,
    away_score: int = 3,
    game_status: str = "Final",
) -> Game:
    async with TestSessionLocal() as session:
        g = Game(
            mlb_game_id=mlb_game_id,
            date=game_date or date(2026, 5, 20),
            home_team=home_team,
            away_team=away_team,
            home_score=home_score,
            away_score=away_score,
            status=game_status,
        )
        session.add(g)
        await session.commit()
        await session.refresh(g)
        return g


async def _seed_stat(
    player: Player,
    game: Game,
    *,
    at_bats: int = 4,
    hits: int = 2,
    home_runs: int = 1,
    rbis: int = 2,
    batting_avg: float = 0.289,
    on_base_pct: float = 0.342,
    slugging_pct: float = 0.512,
) -> BattingStats:
    async with TestSessionLocal() as session:
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
        session.add(bs)
        await session.commit()
        await session.refresh(bs)
        return bs


# ══════════════════════════════════════════════════════════════════════════════
# Player endpoints
# ══════════════════════════════════════════════════════════════════════════════


class TestPlayerEndpoints:
    # ── RBAC ──────────────────────────────────────────────────────────────────

    async def test_list_players_requires_auth(self, client: AsyncClient):
        resp = await client.get("/api/v1/players")
        assert resp.status_code == 403

    async def test_viewer_can_list_players(
        self, client: AsyncClient, viewer_headers: dict
    ):
        await _seed_player()
        resp = await client.get("/api/v1/players", headers=viewer_headers)
        assert resp.status_code == 200

    # ── List / pagination ─────────────────────────────────────────────────────

    async def test_list_players_empty(
        self, client: AsyncClient, viewer_headers: dict
    ):
        resp = await client.get("/api/v1/players", headers=viewer_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["items"] == []

    async def test_list_players_returns_all(
        self, client: AsyncClient, viewer_headers: dict
    ):
        await _seed_player(mlb_id=1, full_name="Alpha Player", team="Team A", position="OF")
        await _seed_player(mlb_id=2, full_name="Beta Player", team="Team B", position="1B")

        resp = await client.get("/api/v1/players", headers=viewer_headers)
        body = resp.json()
        assert body["total"] == 2
        assert len(body["items"]) == 2

    async def test_list_players_pagination(
        self, client: AsyncClient, viewer_headers: dict
    ):
        for i in range(5):
            await _seed_player(mlb_id=100 + i, full_name=f"Player {i}", team="T", position="OF")

        resp = await client.get(
            "/api/v1/players?limit=2&offset=0", headers=viewer_headers
        )
        body = resp.json()
        assert body["total"] == 5
        assert len(body["items"]) == 2
        assert body["limit"] == 2
        assert body["offset"] == 0

        resp2 = await client.get(
            "/api/v1/players?limit=2&offset=2", headers=viewer_headers
        )
        assert len(resp2.json()["items"]) == 2

    async def test_list_players_filter_by_team(
        self, client: AsyncClient, viewer_headers: dict
    ):
        await _seed_player(mlb_id=10, full_name="A", team="Philadelphia Phillies", position="SS")
        await _seed_player(mlb_id=11, full_name="B", team="Cincinnati Reds", position="SS")

        resp = await client.get(
            "/api/v1/players?team=Phillies", headers=viewer_headers
        )
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["team"] == "Philadelphia Phillies"

    async def test_list_players_filter_by_position(
        self, client: AsyncClient, viewer_headers: dict
    ):
        await _seed_player(mlb_id=20, full_name="C", team="T", position="SS")
        await _seed_player(mlb_id=21, full_name="D", team="T", position="1B")
        await _seed_player(mlb_id=22, full_name="E", team="T", position="OF")

        resp = await client.get(
            "/api/v1/players?position=SS", headers=viewer_headers
        )
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["position"] == "SS"

    async def test_list_players_sort_by_team_desc(
        self, client: AsyncClient, viewer_headers: dict
    ):
        await _seed_player(mlb_id=30, full_name="P1", team="Zzz Team", position="OF")
        await _seed_player(mlb_id=31, full_name="P2", team="Aaa Team", position="OF")

        resp = await client.get(
            "/api/v1/players?sort_by=team&sort_order=desc", headers=viewer_headers
        )
        items = resp.json()["items"]
        assert items[0]["team"] == "Zzz Team"

    # ── Search ────────────────────────────────────────────────────────────────

    async def test_search_players_partial_match(
        self, client: AsyncClient, viewer_headers: dict
    ):
        await _seed_player(mlb_id=40, full_name="Trea Turner", team="PHI", position="SS")
        await _seed_player(mlb_id=41, full_name="Bryce Harper", team="PHI", position="1B")

        resp = await client.get(
            "/api/v1/players/search?q=Trea", headers=viewer_headers
        )
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["full_name"] == "Trea Turner"

    async def test_search_players_case_insensitive(
        self, client: AsyncClient, viewer_headers: dict
    ):
        await _seed_player(mlb_id=50, full_name="Elly De La Cruz", team="CIN", position="SS")

        resp = await client.get(
            "/api/v1/players/search?q=elly", headers=viewer_headers
        )
        assert resp.json()["total"] == 1

    async def test_search_players_no_results(
        self, client: AsyncClient, viewer_headers: dict
    ):
        resp = await client.get(
            "/api/v1/players/search?q=zzznobody", headers=viewer_headers
        )
        body = resp.json()
        assert body["total"] == 0
        assert body["items"] == []

    async def test_search_requires_q_param(
        self, client: AsyncClient, viewer_headers: dict
    ):
        resp = await client.get("/api/v1/players/search", headers=viewer_headers)
        assert resp.status_code == 422

    # ── Single player detail ──────────────────────────────────────────────────

    async def test_get_player_returns_career_stats(
        self, client: AsyncClient, viewer_headers: dict
    ):
        player = await _seed_player()
        game = await _seed_game()
        await _seed_stat(player, game, at_bats=4, hits=2, home_runs=1, rbis=2)

        resp = await client.get(
            f"/api/v1/players/{player.id}", headers=viewer_headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == player.id
        assert body["full_name"] == "Trea Turner"

        cs = body["career_stats"]
        assert cs["games_played"] == 1
        assert cs["total_at_bats"] == 4
        assert cs["total_hits"] == 2
        assert cs["total_home_runs"] == 1
        assert cs["total_rbis"] == 2
        # career avg = 2/4 = 0.5
        assert cs["career_batting_avg"] == pytest.approx(0.5)

    async def test_get_player_career_stats_multiple_games(
        self, client: AsyncClient, viewer_headers: dict
    ):
        player = await _seed_player()
        game1 = await _seed_game(mlb_game_id=1001, game_date=date(2026, 5, 19))
        game2 = await _seed_game(mlb_game_id=1002, game_date=date(2026, 5, 20))
        await _seed_stat(player, game1, at_bats=4, hits=1)
        await _seed_stat(player, game2, at_bats=3, hits=2)

        resp = await client.get(
            f"/api/v1/players/{player.id}", headers=viewer_headers
        )
        cs = resp.json()["career_stats"]
        assert cs["games_played"] == 2
        assert cs["total_at_bats"] == 7
        assert cs["total_hits"] == 3
        # Endpoint rounds to 3 dp: round(3/7, 3) = 0.429
        assert cs["career_batting_avg"] == pytest.approx(3 / 7, abs=1e-3)

    async def test_get_player_not_found(
        self, client: AsyncClient, viewer_headers: dict
    ):
        resp = await client.get("/api/v1/players/999999", headers=viewer_headers)
        assert resp.status_code == 404

    # ── Player stats (game-by-game) ───────────────────────────────────────────

    async def test_player_stats_returns_game_lines(
        self, client: AsyncClient, viewer_headers: dict
    ):
        player = await _seed_player()
        game = await _seed_game()
        await _seed_stat(player, game)

        resp = await client.get(
            f"/api/v1/players/{player.id}/stats", headers=viewer_headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        line = body["items"][0]
        assert line["game_date"] == "2026-05-20"
        assert line["home_team"] == "Philadelphia Phillies"
        assert line["at_bats"] == 4
        assert line["hits"] == 2

    async def test_player_stats_date_filter(
        self, client: AsyncClient, viewer_headers: dict
    ):
        player = await _seed_player()
        game_old = await _seed_game(mlb_game_id=2001, game_date=date(2026, 4, 1))
        game_new = await _seed_game(mlb_game_id=2002, game_date=date(2026, 5, 20))
        await _seed_stat(player, game_old)
        await _seed_stat(player, game_new)

        resp = await client.get(
            f"/api/v1/players/{player.id}/stats?from_date=2026-05-01",
            headers=viewer_headers,
        )
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["game_date"] == "2026-05-20"

    async def test_player_stats_not_found(
        self, client: AsyncClient, viewer_headers: dict
    ):
        resp = await client.get(
            "/api/v1/players/999999/stats", headers=viewer_headers
        )
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# Game endpoints
# ══════════════════════════════════════════════════════════════════════════════


class TestGameEndpoints:
    # ── RBAC ──────────────────────────────────────────────────────────────────

    async def test_list_games_requires_auth(self, client: AsyncClient):
        resp = await client.get("/api/v1/games")
        assert resp.status_code == 403

    async def test_viewer_can_list_games(
        self, client: AsyncClient, viewer_headers: dict
    ):
        resp = await client.get("/api/v1/games", headers=viewer_headers)
        assert resp.status_code == 200

    # ── List / pagination ─────────────────────────────────────────────────────

    async def test_list_games_empty(
        self, client: AsyncClient, viewer_headers: dict
    ):
        resp = await client.get("/api/v1/games", headers=viewer_headers)
        body = resp.json()
        assert body["total"] == 0
        assert body["items"] == []

    async def test_list_games_returns_all(
        self, client: AsyncClient, viewer_headers: dict
    ):
        await _seed_game(mlb_game_id=3001, game_date=date(2026, 5, 20))
        await _seed_game(mlb_game_id=3002, game_date=date(2026, 5, 19))

        resp = await client.get("/api/v1/games", headers=viewer_headers)
        body = resp.json()
        assert body["total"] == 2

    async def test_list_games_pagination(
        self, client: AsyncClient, viewer_headers: dict
    ):
        for i in range(5):
            await _seed_game(
                mlb_game_id=4000 + i,
                game_date=date(2026, 5, 20) - timedelta(days=i),
            )

        resp = await client.get(
            "/api/v1/games?limit=3&offset=0", headers=viewer_headers
        )
        body = resp.json()
        assert body["total"] == 5
        assert len(body["items"]) == 3

    async def test_list_games_filter_by_exact_date(
        self, client: AsyncClient, viewer_headers: dict
    ):
        await _seed_game(mlb_game_id=5001, game_date=date(2026, 5, 20))
        await _seed_game(mlb_game_id=5002, game_date=date(2026, 5, 19))

        resp = await client.get(
            "/api/v1/games?date=2026-05-20", headers=viewer_headers
        )
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["mlb_game_id"] == 5001

    async def test_list_games_filter_by_date_range(
        self, client: AsyncClient, viewer_headers: dict
    ):
        await _seed_game(mlb_game_id=6001, game_date=date(2026, 5, 18))
        await _seed_game(mlb_game_id=6002, game_date=date(2026, 5, 19))
        await _seed_game(mlb_game_id=6003, game_date=date(2026, 5, 20))

        resp = await client.get(
            "/api/v1/games?from_date=2026-05-19&to_date=2026-05-19",
            headers=viewer_headers,
        )
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["mlb_game_id"] == 6002

    async def test_list_games_filter_by_team(
        self, client: AsyncClient, viewer_headers: dict
    ):
        await _seed_game(
            mlb_game_id=7001,
            game_date=date(2026, 5, 20),
            home_team="Philadelphia Phillies",
            away_team="Cincinnati Reds",
        )
        await _seed_game(
            mlb_game_id=7002,
            game_date=date(2026, 5, 20),
            home_team="New York Yankees",
            away_team="Boston Red Sox",
        )

        # Team filter matches home OR away
        resp = await client.get(
            "/api/v1/games?team=Phillies", headers=viewer_headers
        )
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["mlb_game_id"] == 7001

    async def test_list_games_filter_by_status(
        self, client: AsyncClient, viewer_headers: dict
    ):
        await _seed_game(mlb_game_id=8001, game_date=date(2026, 5, 20), game_status="Final")
        await _seed_game(mlb_game_id=8002, game_date=date(2026, 5, 20), game_status="Scheduled")

        resp = await client.get(
            "/api/v1/games?status=Final", headers=viewer_headers
        )
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["status"] == "Final"

    # ── Single game with boxscore ─────────────────────────────────────────────

    async def test_get_game_detail(
        self, client: AsyncClient, viewer_headers: dict
    ):
        player = await _seed_player()
        game = await _seed_game()
        await _seed_stat(player, game)

        resp = await client.get(
            f"/api/v1/games/{game.id}", headers=viewer_headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["mlb_game_id"] == game.mlb_game_id
        assert body["home_team"] == "Philadelphia Phillies"
        assert body["home_score"] == 7

        boxscore = body["boxscore"]
        assert len(boxscore) == 1
        line = boxscore[0]
        assert line["full_name"] == "Trea Turner"
        assert line["at_bats"] == 4
        assert line["hits"] == 2

    async def test_get_game_boxscore_multi_player(
        self, client: AsyncClient, viewer_headers: dict
    ):
        game = await _seed_game()
        p1 = await _seed_player(mlb_id=100, full_name="Alpha", team="PHI", position="SS")
        p2 = await _seed_player(mlb_id=101, full_name="Beta", team="CIN", position="OF")
        await _seed_stat(p1, game, hits=2)
        await _seed_stat(p2, game, hits=0)

        resp = await client.get(
            f"/api/v1/games/{game.id}", headers=viewer_headers
        )
        assert len(resp.json()["boxscore"]) == 2

    async def test_get_game_not_found(
        self, client: AsyncClient, viewer_headers: dict
    ):
        resp = await client.get("/api/v1/games/999999", headers=viewer_headers)
        assert resp.status_code == 404

    # ── Today's schedule ──────────────────────────────────────────────────────

    async def test_get_todays_games(
        self, client: AsyncClient, viewer_headers: dict
    ):
        today = date.today()
        await _seed_game(mlb_game_id=9001, game_date=today)
        await _seed_game(mlb_game_id=9002, game_date=today - timedelta(days=1))

        resp = await client.get("/api/v1/games/today", headers=viewer_headers)
        assert resp.status_code == 200
        body = resp.json()
        # Only today's game is returned
        assert body["total"] == 1
        assert body["items"][0]["mlb_game_id"] == 9001

    async def test_todays_games_empty_when_none_today(
        self, client: AsyncClient, viewer_headers: dict
    ):
        # Seed a game for yesterday only
        await _seed_game(
            mlb_game_id=9010,
            game_date=date.today() - timedelta(days=1),
        )
        resp = await client.get("/api/v1/games/today", headers=viewer_headers)
        assert resp.json()["total"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# Cross-resource integration
# ══════════════════════════════════════════════════════════════════════════════


class TestIntegration:
    async def test_player_stats_includes_correct_game_info(
        self, client: AsyncClient, viewer_headers: dict
    ):
        """Player stats lines include the full game context."""
        player = await _seed_player()
        game = await _seed_game(
            home_team="Boston Red Sox",
            away_team="New York Yankees",
            home_score=5,
            away_score=3,
            game_status="Final",
        )
        await _seed_stat(player, game, at_bats=3, hits=1, home_runs=0, rbis=1)

        resp = await client.get(
            f"/api/v1/players/{player.id}/stats", headers=viewer_headers
        )
        line = resp.json()["items"][0]
        assert line["home_team"] == "Boston Red Sox"
        assert line["away_team"] == "New York Yankees"
        assert line["home_score"] == 5
        assert line["game_status"] == "Final"
        assert line["hits"] == 1

    async def test_game_detail_and_player_stats_consistent(
        self, client: AsyncClient, viewer_headers: dict
    ):
        """
        The same stat row appears in both the game's boxscore and the
        player's game-log — both must agree on at_bats and hits.
        """
        player = await _seed_player()
        game = await _seed_game()
        await _seed_stat(player, game, at_bats=4, hits=3)

        game_resp = await client.get(
            f"/api/v1/games/{game.id}", headers=viewer_headers
        )
        player_resp = await client.get(
            f"/api/v1/players/{player.id}/stats", headers=viewer_headers
        )

        boxscore_line = game_resp.json()["boxscore"][0]
        stat_line = player_resp.json()["items"][0]

        assert boxscore_line["at_bats"] == stat_line["at_bats"] == 4
        assert boxscore_line["hits"] == stat_line["hits"] == 3
