"""
Task 4.3 — Comprehensive API tests with a realistic shared fixture dataset.

Why this file exists
────────────────────
The existing test_players_games.py and test_stats.py seed 1–2 rows of data
per individual test.  That's enough to verify happy-path logic but not enough
to assert:
  • exact pagination counts with a real data volume
  • precise filter cardinalities (team="Phillies" → exactly 5 players)
  • correct analytical ordering across a varied dataset
  • formula math with fully-known inputs (league avg, career avg, recent avg)
  • positive RBAC assertions ("viewer CAN read /players")

This file provides those guarantees via ``rich_dataset``, a shared
function-scoped fixture that seeds 11 players × 5 games = 55 stat rows
before each test and is cleaned up by the autouse ``clean_tables`` fixture.

Dataset summary
───────────────
Teams / players
  Philadelphia Phillies (5): Turner (SS), Harper (1B), Schwarber (LF),
                              Castellanos (RF), Realmuto (C)
  New York Yankees      (3): Judge (RF), Soto (LF), Volpe (SS)
  Cincinnati Reds       (3): De La Cruz (SS), Steer (3B), Friedl (CF)

Games  (all Final, 2026-05-15 → 2026-05-19)
  G9001  PHI (home) 7  CIN (away) 3   2026-05-15
  G9002  PHI (home) 4  CIN (away) 2   2026-05-16
  G9003  NYY (home) 5  PHI (away) 2   2026-05-17
  G9004  NYY (home) 3  CIN (away) 1   2026-05-18
  G9005  PHI (home) 6  NYY (away) 4   2026-05-19

Every player appears in every game → 55 batting stat rows.

Key known values (used in exact assertions)
  Turner career avg  = 10 H / 20 AB = .500  (hot streak)
  Soto   career avg  = 10 H / 20 AB = .500  (hot streak)
  Judge  career HR   = 10  (2 × 5 games)    (HR / RBI leader)
  De La Cruz avg     = 0  H / 20 AB = .000  (cold streak)
  League avg         = 55 H / 220 AB = .250

  Hit-probability for Turner
    recent_avg = career_avg = .500  (all games within 30 days)
    league_avg = .250
    p = 0.5×.500 + 0.3×.500 + 0.2×.250 = 0.450

  Team batting averages (stat=batting_avg)
    NYY: 20 H / 60 AB = .333   (rank 1)
    PHI: 30 H / 100 AB = .300  (rank 2)
    CIN:  5 H / 60 AB = .083   (rank 3)
"""

import math
from datetime import date

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.models.batting_stats import BattingStats
from app.models.game import Game
from app.models.player import Player
from tests.conftest import TestSessionLocal

# ── Fixture dataset definition ────────────────────────────────────────────────

# (mlb_id, full_name, team, position, at_bats, hits, home_runs, rbis, obp, slg)
_PLAYER_PROFILES = [
    # Philadelphia Phillies
    (9101, "Trea Turner",       "Philadelphia Phillies", "SS", 4, 2, 0, 1, 0.400, 0.500),
    (9102, "Bryce Harper",      "Philadelphia Phillies", "1B", 4, 1, 1, 2, 0.360, 0.540),
    (9103, "Kyle Schwarber",    "Philadelphia Phillies", "LF", 4, 1, 1, 2, 0.370, 0.640),
    (9104, "Nick Castellanos",  "Philadelphia Phillies", "RF", 4, 1, 0, 1, 0.320, 0.310),
    (9105, "J.T. Realmuto",     "Philadelphia Phillies", "C",  4, 1, 0, 1, 0.310, 0.300),
    # New York Yankees
    (9106, "Aaron Judge",       "New York Yankees",      "RF", 4, 1, 2, 3, 0.320, 0.670),
    (9107, "Juan Soto",         "New York Yankees",      "LF", 4, 2, 0, 0, 0.400, 0.420),
    (9108, "Anthony Volpe",     "New York Yankees",      "SS", 4, 1, 0, 1, 0.310, 0.300),
    # Cincinnati Reds
    (9109, "Elly De La Cruz",   "Cincinnati Reds",       "SS", 4, 0, 0, 0, 0.100, 0.100),
    (9110, "Spencer Steer",     "Cincinnati Reds",       "3B", 4, 0, 0, 0, 0.120, 0.100),
    (9111, "TJ Friedl",         "Cincinnati Reds",       "CF", 4, 1, 0, 0, 0.290, 0.280),
]

# (mlb_game_id, date, home_team, away_team, home_score, away_score)
_GAME_DEFS = [
    (9001, date(2026, 5, 15), "Philadelphia Phillies", "Cincinnati Reds",      7, 3),
    (9002, date(2026, 5, 16), "Philadelphia Phillies", "Cincinnati Reds",      4, 2),
    (9003, date(2026, 5, 17), "New York Yankees",      "Philadelphia Phillies",5, 2),
    (9004, date(2026, 5, 18), "New York Yankees",      "Cincinnati Reds",      3, 1),
    (9005, date(2026, 5, 19), "Philadelphia Phillies", "New York Yankees",     6, 4),
]

# Derived constants (used in test assertions)
_N_PLAYERS   = len(_PLAYER_PROFILES)        # 11
_N_GAMES     = len(_GAME_DEFS)              # 5
_N_STATS     = _N_PLAYERS * _N_GAMES       # 55
_TOTAL_AB    = sum(p[4] for p in _PLAYER_PROFILES) * _N_GAMES  # 220
_TOTAL_HITS  = sum(p[5] for p in _PLAYER_PROFILES) * _N_GAMES  # 55
_LEAGUE_AVG  = _TOTAL_HITS / _TOTAL_AB      # 0.250

# Per-player career totals (5 games each)
_TURNER_H    = 2 * _N_GAMES   # 10
_TURNER_AB   = 4 * _N_GAMES   # 20
_JUDGE_HR    = 2 * _N_GAMES   # 10
_JUDGE_RBI   = 3 * _N_GAMES   # 15


# ── Shared fixture ────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def rich_dataset() -> dict:
    """
    Seed the complete dataset described in the module docstring.
    Returns a dict with ``players`` (name → Player) and ``games``
    (mlb_game_id → Game) for use in test assertions.
    """
    async with TestSessionLocal() as session:
        # Players
        players: dict[str, Player] = {}
        for mlb_id, name, team, pos, *_ in _PLAYER_PROFILES:
            p = Player(mlb_id=mlb_id, full_name=name, team=team, position=pos)
            session.add(p)
        await session.flush()

        for p in (await session.execute(select(Player))).scalars().all():
            players[p.full_name] = p

        # Games
        games: dict[int, Game] = {}
        for gid, gdate, home, away, hs, as_ in _GAME_DEFS:
            g = Game(
                mlb_game_id=gid,
                date=gdate,
                home_team=home,
                away_team=away,
                home_score=hs,
                away_score=as_,
                status="Final",
            )
            session.add(g)
        await session.flush()

        for g in (await session.execute(select(Game))).scalars().all():
            games[g.mlb_game_id] = g

        # Batting stats — every player in every game
        profile_map = {
            name: (ab, h, hr, rbi, obp, slg)
            for _, name, _, _, ab, h, hr, rbi, obp, slg in _PLAYER_PROFILES
        }
        for player in players.values():
            ab, h, hr, rbi, obp, slg = profile_map[player.full_name]
            avg = h / ab if ab > 0 else None
            for game in games.values():
                session.add(
                    BattingStats(
                        player_id=player.id,
                        game_id=game.id,
                        at_bats=ab,
                        hits=h,
                        home_runs=hr,
                        rbis=rbi,
                        batting_avg=avg,
                        on_base_pct=obp,
                        slugging_pct=slg,
                    )
                )

        await session.commit()

    return {"players": players, "games": games}


# ══════════════════════════════════════════════════════════════════════════════
# Pagination
# ══════════════════════════════════════════════════════════════════════════════


class TestPagination:
    """Verify limit / offset / total behave correctly with 11 real players."""

    async def test_players_total_count(
        self, client: AsyncClient, viewer_headers: dict, rich_dataset: dict
    ):
        resp = await client.get("/api/v1/players", headers=viewer_headers)
        assert resp.status_code == 200
        assert resp.json()["total"] == _N_PLAYERS

    async def test_players_first_page(
        self, client: AsyncClient, viewer_headers: dict, rich_dataset: dict
    ):
        resp = await client.get(
            "/api/v1/players?limit=5&offset=0", headers=viewer_headers
        )
        body = resp.json()
        assert body["total"] == _N_PLAYERS
        assert len(body["items"]) == 5
        assert body["limit"] == 5
        assert body["offset"] == 0

    async def test_players_second_page(
        self, client: AsyncClient, viewer_headers: dict, rich_dataset: dict
    ):
        resp = await client.get(
            "/api/v1/players?limit=5&offset=5", headers=viewer_headers
        )
        body = resp.json()
        assert body["total"] == _N_PLAYERS
        assert len(body["items"]) == 5

    async def test_players_last_partial_page(
        self, client: AsyncClient, viewer_headers: dict, rich_dataset: dict
    ):
        """11 players, limit=5, offset=10 → last page has 1 item."""
        resp = await client.get(
            "/api/v1/players?limit=5&offset=10", headers=viewer_headers
        )
        body = resp.json()
        assert body["total"] == _N_PLAYERS
        assert len(body["items"]) == 1

    async def test_players_no_items_beyond_total(
        self, client: AsyncClient, viewer_headers: dict, rich_dataset: dict
    ):
        resp = await client.get(
            "/api/v1/players?limit=5&offset=100", headers=viewer_headers
        )
        body = resp.json()
        assert body["total"] == _N_PLAYERS
        assert body["items"] == []

    async def test_games_total_count(
        self, client: AsyncClient, viewer_headers: dict, rich_dataset: dict
    ):
        resp = await client.get("/api/v1/games", headers=viewer_headers)
        assert resp.json()["total"] == _N_GAMES

    async def test_games_pagination(
        self, client: AsyncClient, viewer_headers: dict, rich_dataset: dict
    ):
        resp = await client.get(
            "/api/v1/games?limit=3&offset=0", headers=viewer_headers
        )
        body = resp.json()
        assert body["total"] == _N_GAMES
        assert len(body["items"]) == 3

    async def test_player_stats_total_count(
        self, client: AsyncClient, viewer_headers: dict, rich_dataset: dict
    ):
        """Turner appears in all 5 games → total=5."""
        turner_id = rich_dataset["players"]["Trea Turner"].id
        resp = await client.get(
            f"/api/v1/players/{turner_id}/stats", headers=viewer_headers
        )
        assert resp.json()["total"] == _N_GAMES

    async def test_player_stats_pagination(
        self, client: AsyncClient, viewer_headers: dict, rich_dataset: dict
    ):
        turner_id = rich_dataset["players"]["Trea Turner"].id
        resp = await client.get(
            f"/api/v1/players/{turner_id}/stats?limit=2&offset=0",
            headers=viewer_headers,
        )
        body = resp.json()
        assert body["total"] == _N_GAMES
        assert len(body["items"]) == 2


# ══════════════════════════════════════════════════════════════════════════════
# Filters
# ══════════════════════════════════════════════════════════════════════════════


class TestFilters:
    """Verify filter parameters return exact known subset counts."""

    # ── Player filters ────────────────────────────────────────────────────────

    async def test_filter_players_phillies(
        self, client: AsyncClient, viewer_headers: dict, rich_dataset: dict
    ):
        resp = await client.get(
            "/api/v1/players?team=Phillies", headers=viewer_headers
        )
        body = resp.json()
        assert body["total"] == 5
        for p in body["items"]:
            assert "Philadelphia Phillies" in p["team"]

    async def test_filter_players_yankees(
        self, client: AsyncClient, viewer_headers: dict, rich_dataset: dict
    ):
        resp = await client.get(
            "/api/v1/players?team=Yankees", headers=viewer_headers
        )
        assert resp.json()["total"] == 3

    async def test_filter_players_reds(
        self, client: AsyncClient, viewer_headers: dict, rich_dataset: dict
    ):
        resp = await client.get(
            "/api/v1/players?team=Reds", headers=viewer_headers
        )
        assert resp.json()["total"] == 3

    async def test_filter_players_position_ss(
        self, client: AsyncClient, viewer_headers: dict, rich_dataset: dict
    ):
        """SS: Turner (PHI), Volpe (NYY), De La Cruz (CIN) = 3 players."""
        resp = await client.get(
            "/api/v1/players?position=SS", headers=viewer_headers
        )
        assert resp.json()["total"] == 3

    async def test_filter_players_team_and_position(
        self, client: AsyncClient, viewer_headers: dict, rich_dataset: dict
    ):
        """PHI + SS → only Trea Turner."""
        resp = await client.get(
            "/api/v1/players?team=Phillies&position=SS", headers=viewer_headers
        )
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["full_name"] == "Trea Turner"

    async def test_search_partial_name(
        self, client: AsyncClient, viewer_headers: dict, rich_dataset: dict
    ):
        resp = await client.get(
            "/api/v1/players/search?q=Judge", headers=viewer_headers
        )
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["full_name"] == "Aaron Judge"

    async def test_search_partial_name_multiple_results(
        self, client: AsyncClient, viewer_headers: dict, rich_dataset: dict
    ):
        """'er' matches Turner, Harper, Schwarber, Steer = 4 players."""
        resp = await client.get(
            "/api/v1/players/search?q=er", headers=viewer_headers
        )
        assert resp.json()["total"] >= 2  # at minimum Turner and Harper

    # ── Game filters ──────────────────────────────────────────────────────────

    async def test_filter_games_by_exact_date(
        self, client: AsyncClient, viewer_headers: dict, rich_dataset: dict
    ):
        resp = await client.get(
            "/api/v1/games?date=2026-05-17", headers=viewer_headers
        )
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["home_team"] == "New York Yankees"

    async def test_filter_games_by_date_range(
        self, client: AsyncClient, viewer_headers: dict, rich_dataset: dict
    ):
        """from=2026-05-17 to=2026-05-18 → G9003 + G9004 = 2 games."""
        resp = await client.get(
            "/api/v1/games?from_date=2026-05-17&to_date=2026-05-18",
            headers=viewer_headers,
        )
        assert resp.json()["total"] == 2

    async def test_filter_games_by_phillies(
        self, client: AsyncClient, viewer_headers: dict, rich_dataset: dict
    ):
        """PHI appears in G9001, G9002 (home), G9003 (away), G9005 (home) = 4 games."""
        resp = await client.get(
            "/api/v1/games?team=Phillies", headers=viewer_headers
        )
        assert resp.json()["total"] == 4

    async def test_filter_games_by_reds(
        self, client: AsyncClient, viewer_headers: dict, rich_dataset: dict
    ):
        """CIN appears in G9001, G9002 (away), G9004 (away) = 3 games."""
        resp = await client.get(
            "/api/v1/games?team=Reds", headers=viewer_headers
        )
        assert resp.json()["total"] == 3

    async def test_filter_games_by_status(
        self, client: AsyncClient, viewer_headers: dict, rich_dataset: dict
    ):
        resp = await client.get(
            "/api/v1/games?status=Final", headers=viewer_headers
        )
        assert resp.json()["total"] == _N_GAMES  # all 5 are Final

    async def test_filter_player_stats_from_date(
        self, client: AsyncClient, viewer_headers: dict, rich_dataset: dict
    ):
        """Turner stats from 2026-05-17 onwards → G9003, G9004, G9005 = 3 rows."""
        turner_id = rich_dataset["players"]["Trea Turner"].id
        resp = await client.get(
            f"/api/v1/players/{turner_id}/stats?from_date=2026-05-17",
            headers=viewer_headers,
        )
        assert resp.json()["total"] == 3

    async def test_filter_player_stats_to_date(
        self, client: AsyncClient, viewer_headers: dict, rich_dataset: dict
    ):
        """Turner stats up to 2026-05-16 → G9001, G9002 = 2 rows."""
        turner_id = rich_dataset["players"]["Trea Turner"].id
        resp = await client.get(
            f"/api/v1/players/{turner_id}/stats?to_date=2026-05-16",
            headers=viewer_headers,
        )
        assert resp.json()["total"] == 2

    async def test_filter_player_stats_date_range(
        self, client: AsyncClient, viewer_headers: dict, rich_dataset: dict
    ):
        turner_id = rich_dataset["players"]["Trea Turner"].id
        resp = await client.get(
            f"/api/v1/players/{turner_id}/stats"
            "?from_date=2026-05-16&to_date=2026-05-17",
            headers=viewer_headers,
        )
        assert resp.json()["total"] == 2


# ══════════════════════════════════════════════════════════════════════════════
# Batting leaders — exact ordering
# ══════════════════════════════════════════════════════════════════════════════


class TestBattingLeadersOrdering:
    """Verify leaderboard order using the known fixed dataset."""

    async def test_batting_avg_top_players_are_turner_and_soto(
        self, client: AsyncClient, analyst_headers: dict, rich_dataset: dict
    ):
        resp = await client.get(
            "/api/v1/stats/leaders?stat=batting_avg&limit=5",
            headers=analyst_headers,
        )
        assert resp.status_code == 200
        names = [e["full_name"] for e in resp.json()["leaders"]]
        # Turner and Soto both bat .500; both must appear at the top
        assert "Trea Turner" in names[:2]
        assert "Juan Soto" in names[:2]

    async def test_batting_avg_cold_players_are_last(
        self, client: AsyncClient, analyst_headers: dict, rich_dataset: dict
    ):
        resp = await client.get(
            "/api/v1/stats/leaders?stat=batting_avg&limit=11",
            headers=analyst_headers,
        )
        names = [e["full_name"] for e in resp.json()["leaders"]]
        # De La Cruz and Steer (.000) must be at the bottom
        assert names[-2:] == sorted(["Elly De La Cruz", "Spencer Steer"]) or \
               set(names[-2:]) == {"Elly De La Cruz", "Spencer Steer"}

    async def test_batting_avg_values_descending(
        self, client: AsyncClient, analyst_headers: dict, rich_dataset: dict
    ):
        resp = await client.get(
            "/api/v1/stats/leaders?stat=batting_avg&limit=11",
            headers=analyst_headers,
        )
        values = [e["value"] for e in resp.json()["leaders"] if e["value"] is not None]
        assert values == sorted(values, reverse=True), "Leaders must be descending"

    async def test_home_run_leader_is_judge(
        self, client: AsyncClient, analyst_headers: dict, rich_dataset: dict
    ):
        resp = await client.get(
            "/api/v1/stats/leaders?stat=home_runs&limit=3",
            headers=analyst_headers,
        )
        leader = resp.json()["leaders"][0]
        assert leader["full_name"] == "Aaron Judge"
        assert leader["value"] == pytest.approx(_JUDGE_HR)
        assert leader["rank"] == 1

    async def test_rbi_leader_is_judge(
        self, client: AsyncClient, analyst_headers: dict, rich_dataset: dict
    ):
        resp = await client.get(
            "/api/v1/stats/leaders?stat=rbis&limit=3", headers=analyst_headers
        )
        leader = resp.json()["leaders"][0]
        assert leader["full_name"] == "Aaron Judge"
        assert leader["value"] == pytest.approx(_JUDGE_RBI)

    async def test_hits_leaders_include_turner_and_soto(
        self, client: AsyncClient, analyst_headers: dict, rich_dataset: dict
    ):
        resp = await client.get(
            "/api/v1/stats/leaders?stat=hits&limit=3", headers=analyst_headers
        )
        names = {e["full_name"] for e in resp.json()["leaders"]}
        assert "Trea Turner" in names
        assert "Juan Soto" in names

    async def test_display_value_avg_format(
        self, client: AsyncClient, analyst_headers: dict, rich_dataset: dict
    ):
        """batting_avg display values must start with '.' and be 4 chars."""
        resp = await client.get(
            "/api/v1/stats/leaders?stat=batting_avg", headers=analyst_headers
        )
        for entry in resp.json()["leaders"]:
            dv = entry["display_value"]
            assert dv == "---" or (dv.startswith(".") and len(dv) == 4), \
                f"Bad display_value: {dv!r}"

    async def test_days_filter_limits_leaders(
        self, client: AsyncClient, analyst_headers: dict, rich_dataset: dict
    ):
        """
        All 5 games are 2026-05-15 → 2026-05-19 (all within 30 days of today
        2026-05-22).  Using days=3 cuts to only the most recent game (05-19).
        Players still have 4 AB → qualifies for MIN_AB=10? No — only 4 AB in
        the 3-day window, below the 10 AB threshold → leaders is empty.
        """
        resp = await client.get(
            "/api/v1/stats/leaders?stat=batting_avg&days=3",
            headers=analyst_headers,
        )
        # Only 1 game (05-19) in 3-day window → 4 AB each → below 10 AB minimum
        assert resp.json()["leaders"] == []

    async def test_team_rankings_order(
        self, client: AsyncClient, analyst_headers: dict, rich_dataset: dict
    ):
        """
        Known team batting averages:
          NYY: 20 H / 60 AB = .333 (rank 1)
          PHI: 30 H / 100 AB = .300 (rank 2)
          CIN:  5 H / 60 AB = .083 (rank 3)
        """
        resp = await client.get(
            "/api/v1/stats/teams?stat=batting_avg", headers=analyst_headers
        )
        assert resp.status_code == 200
        rankings = resp.json()["rankings"]
        assert len(rankings) == 3

        by_team = {r["team"]: r for r in rankings}
        assert by_team["New York Yankees"]["rank"] == 1
        assert by_team["Philadelphia Phillies"]["rank"] == 2
        assert by_team["Cincinnati Reds"]["rank"] == 3

        assert by_team["New York Yankees"]["value"] == pytest.approx(
            20 / 60, abs=0.001
        )
        assert by_team["Philadelphia Phillies"]["value"] == pytest.approx(
            30 / 100, abs=0.001
        )


# ══════════════════════════════════════════════════════════════════════════════
# Hit probability — exact formula verification
# ══════════════════════════════════════════════════════════════════════════════


class TestHitProbabilityKnownInputs:
    """
    Verify the formula: p = 0.5×recent + 0.3×career + 0.2×league.

    With all 5 games within the 30-day window, recent_avg = career_avg.
    League avg = 55 H / 220 AB = 0.250 (exact, deterministic).
    """

    async def test_turner_exact_probability(
        self, client: AsyncClient, analyst_headers: dict, rich_dataset: dict
    ):
        """
        Turner: recent = career = 0.500, league = 0.250
        expected = 0.5×0.500 + 0.3×0.500 + 0.2×0.250 = 0.450
        """
        turner_id = rich_dataset["players"]["Trea Turner"].id
        resp = await client.get(
            f"/api/v1/stats/hit-probability/{turner_id}",
            headers=analyst_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["recent_avg"] == pytest.approx(0.500, abs=0.001)
        assert body["career_avg"] == pytest.approx(0.500, abs=0.001)
        assert body["league_avg"] == pytest.approx(_LEAGUE_AVG, abs=0.001)
        assert body["hit_probability"] == pytest.approx(0.450, abs=0.001)

    async def test_turner_display_probability(
        self, client: AsyncClient, analyst_headers: dict, rich_dataset: dict
    ):
        turner_id = rich_dataset["players"]["Trea Turner"].id
        resp = await client.get(
            f"/api/v1/stats/hit-probability/{turner_id}",
            headers=analyst_headers,
        )
        assert resp.json()["display_probability"] == "45.0%"

    async def test_turner_confidence_medium(
        self, client: AsyncClient, analyst_headers: dict, rich_dataset: dict
    ):
        """20 recent AB → 15 ≤ 20 < 50 → 'medium' confidence."""
        turner_id = rich_dataset["players"]["Trea Turner"].id
        resp = await client.get(
            f"/api/v1/stats/hit-probability/{turner_id}",
            headers=analyst_headers,
        )
        assert resp.json()["confidence"] == "medium"

    async def test_turner_ci_contains_probability(
        self, client: AsyncClient, analyst_headers: dict, rich_dataset: dict
    ):
        turner_id = rich_dataset["players"]["Trea Turner"].id
        resp = await client.get(
            f"/api/v1/stats/hit-probability/{turner_id}",
            headers=analyst_headers,
        )
        body = resp.json()
        assert body["ci_lower"] <= body["hit_probability"] <= body["ci_upper"]

    async def test_de_la_cruz_lower_probability_than_turner(
        self, client: AsyncClient, analyst_headers: dict, rich_dataset: dict
    ):
        """
        De La Cruz: recent = career = 0.000
        expected = 0.5×0.000 + 0.3×0.000 + 0.2×0.250 = 0.050
        Turner (0.450) >> De La Cruz (0.050)
        """
        turner_id = rich_dataset["players"]["Trea Turner"].id
        dlc_id = rich_dataset["players"]["Elly De La Cruz"].id

        resp_t = await client.get(
            f"/api/v1/stats/hit-probability/{turner_id}", headers=analyst_headers
        )
        resp_d = await client.get(
            f"/api/v1/stats/hit-probability/{dlc_id}", headers=analyst_headers
        )
        assert resp_t.json()["hit_probability"] > resp_d.json()["hit_probability"]

    async def test_de_la_cruz_exact_probability(
        self, client: AsyncClient, analyst_headers: dict, rich_dataset: dict
    ):
        """
        De La Cruz: recent = career = 0.000, league = 0.250
        expected = 0.2 × 0.250 = 0.050
        """
        dlc_id = rich_dataset["players"]["Elly De La Cruz"].id
        resp = await client.get(
            f"/api/v1/stats/hit-probability/{dlc_id}", headers=analyst_headers
        )
        body = resp.json()
        assert body["hit_probability"] == pytest.approx(0.050, abs=0.001)
        assert body["career_avg"] == pytest.approx(0.0, abs=0.001)

    async def test_judge_probability_uses_league_avg(
        self, client: AsyncClient, analyst_headers: dict, rich_dataset: dict
    ):
        """
        Judge: recent = career = 0.250
        expected = 0.5×0.250 + 0.3×0.250 + 0.2×0.250 = 0.250
        """
        judge_id = rich_dataset["players"]["Aaron Judge"].id
        resp = await client.get(
            f"/api/v1/stats/hit-probability/{judge_id}", headers=analyst_headers
        )
        body = resp.json()
        assert body["hit_probability"] == pytest.approx(0.250, abs=0.001)


# ══════════════════════════════════════════════════════════════════════════════
# Player comparison
# ══════════════════════════════════════════════════════════════════════════════


class TestPlayerComparison:
    """Side-by-side comparison with fully known career stats."""

    async def test_two_player_comparison_structure(
        self, client: AsyncClient, analyst_headers: dict, rich_dataset: dict
    ):
        turner_id = rich_dataset["players"]["Trea Turner"].id
        judge_id = rich_dataset["players"]["Aaron Judge"].id

        resp = await client.post(
            "/api/v1/stats/compare",
            json={"player_ids": [turner_id, judge_id]},
            headers=analyst_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["players"]) == 2
        assert set(body["leaders"].keys()) == {
            "batting_avg", "home_runs", "rbis", "hits", "ops", "recent_avg"
        }

    async def test_three_player_leaders_dict(
        self, client: AsyncClient, analyst_headers: dict, rich_dataset: dict
    ):
        """
        Turner vs Judge vs De La Cruz:
          batting_avg: Turner  (.500)
          home_runs:   Judge   (10)
          rbis:        Judge   (15)
          hits:        Turner  (10)
        """
        turner_id = rich_dataset["players"]["Trea Turner"].id
        judge_id = rich_dataset["players"]["Aaron Judge"].id
        dlc_id = rich_dataset["players"]["Elly De La Cruz"].id

        resp = await client.post(
            "/api/v1/stats/compare",
            json={"player_ids": [turner_id, judge_id, dlc_id]},
            headers=analyst_headers,
        )
        leaders = resp.json()["leaders"]
        assert leaders["batting_avg"] == turner_id
        assert leaders["home_runs"] == judge_id
        assert leaders["rbis"] == judge_id
        assert leaders["hits"] == turner_id

    async def test_career_totals_correct(
        self, client: AsyncClient, analyst_headers: dict, rich_dataset: dict
    ):
        """Verify exact career aggregates for Turner and Judge."""
        turner_id = rich_dataset["players"]["Trea Turner"].id
        judge_id = rich_dataset["players"]["Aaron Judge"].id

        resp = await client.post(
            "/api/v1/stats/compare",
            json={"player_ids": [turner_id, judge_id]},
            headers=analyst_headers,
        )
        by_id = {p["player_id"]: p for p in resp.json()["players"]}

        t = by_id[turner_id]
        assert t["games_played"] == _N_GAMES
        assert t["at_bats"] == _TURNER_AB
        assert t["hits"] == _TURNER_H
        assert t["batting_avg"] == pytest.approx(_TURNER_H / _TURNER_AB, abs=0.001)

        j = by_id[judge_id]
        assert j["home_runs"] == _JUDGE_HR
        assert j["rbis"] == _JUDGE_RBI

    async def test_display_avg_format_in_comparison(
        self, client: AsyncClient, analyst_headers: dict, rich_dataset: dict
    ):
        turner_id = rich_dataset["players"]["Trea Turner"].id
        judge_id = rich_dataset["players"]["Aaron Judge"].id

        resp = await client.post(
            "/api/v1/stats/compare",
            json={"player_ids": [turner_id, judge_id]},
            headers=analyst_headers,
        )
        by_id = {p["player_id"]: p for p in resp.json()["players"]}
        assert by_id[turner_id]["display_avg"] == ".500"
        assert by_id[judge_id]["display_avg"] == ".250"


# ══════════════════════════════════════════════════════════════════════════════
# Hot / cold streaks
# ══════════════════════════════════════════════════════════════════════════════


class TestStreaks:
    """Verify streak detection with the known dataset."""

    async def test_hot_streaks_are_turner_and_soto(
        self, client: AsyncClient, analyst_headers: dict, rich_dataset: dict
    ):
        resp = await client.get(
            "/api/v1/stats/streaks?type=hot&min_games=5", headers=analyst_headers
        )
        assert resp.status_code == 200
        hot_names = {s["full_name"] for s in resp.json()["streaks"]}
        assert "Trea Turner" in hot_names
        assert "Juan Soto" in hot_names

    async def test_hot_streak_avg_is_correct(
        self, client: AsyncClient, analyst_headers: dict, rich_dataset: dict
    ):
        resp = await client.get(
            "/api/v1/stats/streaks?type=hot&min_games=5", headers=analyst_headers
        )
        for entry in resp.json()["streaks"]:
            assert entry["period_avg"] == pytest.approx(0.500, abs=0.001)
            assert entry["streak_type"] == "hot"

    async def test_cold_streaks_are_de_la_cruz_and_steer(
        self, client: AsyncClient, analyst_headers: dict, rich_dataset: dict
    ):
        resp = await client.get(
            "/api/v1/stats/streaks?type=cold&min_games=5", headers=analyst_headers
        )
        cold_names = {s["full_name"] for s in resp.json()["streaks"]}
        assert "Elly De La Cruz" in cold_names
        assert "Spencer Steer" in cold_names

    async def test_cold_streak_avg_is_zero(
        self, client: AsyncClient, analyst_headers: dict, rich_dataset: dict
    ):
        resp = await client.get(
            "/api/v1/stats/streaks?type=cold&min_games=5", headers=analyst_headers
        )
        for entry in resp.json()["streaks"]:
            assert entry["period_avg"] == pytest.approx(0.000, abs=0.001)
            assert entry["streak_type"] == "cold"

    async def test_both_streaks_returns_four_players(
        self, client: AsyncClient, analyst_headers: dict, rich_dataset: dict
    ):
        """Turner, Soto (hot) + De La Cruz, Steer (cold) = 4 total."""
        resp = await client.get(
            "/api/v1/stats/streaks?type=both&min_games=5", headers=analyst_headers
        )
        streaks = resp.json()["streaks"]
        assert len(streaks) == 4

    async def test_average_players_absent_from_streaks(
        self, client: AsyncClient, analyst_headers: dict, rich_dataset: dict
    ):
        """Players with .250 avg (between thresholds) must not appear."""
        resp = await client.get(
            "/api/v1/stats/streaks?type=both&min_games=5", headers=analyst_headers
        )
        streak_names = {s["full_name"] for s in resp.json()["streaks"]}
        for name in ["Bryce Harper", "Aaron Judge", "Anthony Volpe", "TJ Friedl"]:
            assert name not in streak_names, f"{name} should not be on a streak"

    async def test_streaks_sorted_hot_first(
        self, client: AsyncClient, analyst_headers: dict, rich_dataset: dict
    ):
        """type=both → ORDER BY period_avg DESC → hot players first."""
        resp = await client.get(
            "/api/v1/stats/streaks?type=both&min_games=5", headers=analyst_headers
        )
        avgs = [s["period_avg"] for s in resp.json()["streaks"]]
        assert avgs == sorted(avgs, reverse=True)


# ══════════════════════════════════════════════════════════════════════════════
# Role enforcement
# ══════════════════════════════════════════════════════════════════════════════


class TestRoleEnforcement:
    """
    Explicit positive + negative RBAC assertions.

    No seeded fixture needed — RBAC fires before any DB query,
    so we can test with non-existent IDs for the 403 cases.
    """

    # ── Viewer CAN access read-only data endpoints ────────────────────────────

    async def test_viewer_can_list_players(
        self, client: AsyncClient, viewer_headers: dict
    ):
        resp = await client.get("/api/v1/players", headers=viewer_headers)
        assert resp.status_code == 200

    async def test_viewer_can_access_games(
        self, client: AsyncClient, viewer_headers: dict
    ):
        resp = await client.get("/api/v1/games", headers=viewer_headers)
        assert resp.status_code == 200

    async def test_viewer_can_access_games_today(
        self, client: AsyncClient, viewer_headers: dict
    ):
        resp = await client.get("/api/v1/games/today", headers=viewer_headers)
        assert resp.status_code == 200

    async def test_viewer_can_search_players(
        self, client: AsyncClient, viewer_headers: dict
    ):
        resp = await client.get(
            "/api/v1/players/search?q=judge", headers=viewer_headers
        )
        assert resp.status_code == 200

    # ── Viewer CANNOT access analytics ───────────────────────────────────────

    async def test_viewer_blocked_from_stats_leaders(
        self, client: AsyncClient, viewer_headers: dict
    ):
        resp = await client.get("/api/v1/stats/leaders", headers=viewer_headers)
        assert resp.status_code == 403
        assert "analyst" in resp.json()["detail"]

    async def test_viewer_blocked_from_team_rankings(
        self, client: AsyncClient, viewer_headers: dict
    ):
        resp = await client.get("/api/v1/stats/teams", headers=viewer_headers)
        assert resp.status_code == 403

    async def test_viewer_blocked_from_hit_probability(
        self, client: AsyncClient, viewer_headers: dict
    ):
        # RBAC fires before the DB lookup → 403 even for non-existent ID
        resp = await client.get(
            "/api/v1/stats/hit-probability/1", headers=viewer_headers
        )
        assert resp.status_code == 403

    async def test_viewer_blocked_from_streaks(
        self, client: AsyncClient, viewer_headers: dict
    ):
        resp = await client.get("/api/v1/stats/streaks", headers=viewer_headers)
        assert resp.status_code == 403

    async def test_viewer_blocked_from_compare(
        self, client: AsyncClient, viewer_headers: dict
    ):
        resp = await client.post(
            "/api/v1/stats/compare",
            json={"player_ids": [1, 2]},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    # ── Analyst CAN access analytics ─────────────────────────────────────────

    async def test_analyst_can_access_leaders(
        self, client: AsyncClient, analyst_headers: dict
    ):
        resp = await client.get("/api/v1/stats/leaders", headers=analyst_headers)
        assert resp.status_code == 200

    async def test_analyst_can_access_team_rankings(
        self, client: AsyncClient, analyst_headers: dict
    ):
        resp = await client.get("/api/v1/stats/teams", headers=analyst_headers)
        assert resp.status_code == 200

    async def test_analyst_can_access_streaks(
        self, client: AsyncClient, analyst_headers: dict
    ):
        resp = await client.get("/api/v1/stats/streaks", headers=analyst_headers)
        assert resp.status_code == 200

    # ── Unauthenticated gets 403 everywhere ───────────────────────────────────

    async def test_no_token_blocked_from_players(self, client: AsyncClient):
        resp = await client.get("/api/v1/players")
        assert resp.status_code == 403

    async def test_no_token_blocked_from_stats(self, client: AsyncClient):
        resp = await client.get("/api/v1/stats/leaders")
        assert resp.status_code == 403
