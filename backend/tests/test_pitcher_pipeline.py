"""
Phase 8.3 — pitcher data pipeline tests.

Covers:
- MLB client: get_game_pitching_lines (mocked boxscore JSON)
- MLB client: get_probable_pitchers (mocked schedule JSON with hydrate)
- MLB client: _parse_innings handles the '6.1' = 6⅓ convention
- ETL: _upsert_pitcher_player + _upsert_pitcher_game_stats roundtrip
- ETL: recalc_season_pitching_aggregates derives ERA + WHIP correctly
- ETL: upsert_probable_pitchers writes home/away_probable_pitcher_id
- Schema: per-game and season-aggregate rows coexist (partial uniqueness)
- MLB client extracts batSide / pitchHand from /people endpoint
"""
from datetime import date

import httpx
import pytest
import respx

from app.models.game import Game
from app.models.pitcher_stats import PitcherStats
from app.models.player import Player
from app.services.etl import (
    _upsert_pitcher_game_stats,
    _upsert_pitcher_player,
    recalc_season_pitching_aggregates,
    upsert_probable_pitchers,
)
from app.services.mlb_client import MLBClient, PitchingLineInfo
from tests.conftest import TestSessionLocal

# ── _parse_innings ───────────────────────────────────────────────────────────


class TestParseInnings:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("6.0", 6.0),
            ("6.1", pytest.approx(6.333, abs=0.001)),  # 6⅓
            ("6.2", pytest.approx(6.667, abs=0.001)),  # 6⅔
            ("0.0", 0.0),
            (None, 0.0),
            ("not-a-number", 0.0),
        ],
    )
    def test_innings_conversion(self, raw: object, expected: float) -> None:
        assert MLBClient._parse_innings(raw) == expected


# ── Mocked MLB client methods ────────────────────────────────────────────────


_FAKE_BOXSCORE = {
    "teams": {
        "home": {
            "team": {"id": 147, "name": "New York Yankees"},
            "batters": [],
            "pitchers": [592789, 592790],
            "players": {
                "ID592789": {
                    "person": {
                        "id": 592789,
                        "fullName": "Gerrit Cole",
                        "pitchHand": {"code": "R"},
                    },
                    "stats": {
                        "pitching": {
                            "inningsPitched": "7.1",
                            "hits": 4,
                            "earnedRuns": 1,
                            "baseOnBalls": 2,
                            "strikeOuts": 9,
                            "era": "2.85",
                            "whip": "0.93",
                        }
                    },
                },
                "ID592790": {
                    "person": {
                        "id": 592790,
                        "fullName": "Tommy Kahnle",
                        "pitchHand": {"code": "R"},
                    },
                    "stats": {
                        "pitching": {
                            "inningsPitched": "1.0",
                            "hits": 0,
                            "earnedRuns": 0,
                            "baseOnBalls": 0,
                            "strikeOuts": 1,
                            "era": "1.50",
                            "whip": "0.83",
                        }
                    },
                },
            },
        },
        "away": {
            "team": {"id": 111, "name": "Boston Red Sox"},
            "batters": [],
            "pitchers": [],
            "players": {},
        },
    }
}

_FAKE_SCHEDULE_WITH_PROBABLES = {
    "dates": [
        {
            "date": "2026-05-25",
            "games": [
                {
                    "gamePk": 778901,
                    "gameDate": "2026-05-25T23:05:00Z",
                    "teams": {
                        "home": {
                            "team": {"id": 147, "name": "New York Yankees"},
                            "probablePitcher": {"id": 592789, "fullName": "Gerrit Cole"},
                        },
                        "away": {
                            "team": {"id": 111, "name": "Boston Red Sox"},
                            "probablePitcher": {"id": 657241, "fullName": "Brayan Bello"},
                        },
                    },
                },
                {
                    "gamePk": 778902,
                    "gameDate": "2026-05-25T20:10:00Z",
                    "teams": {
                        "home": {"team": {"id": 121, "name": "New York Mets"}, "probablePitcher": None},
                        "away": {"team": {"id": 144, "name": "Atlanta Braves"}, "probablePitcher": None},
                    },
                },
            ],
        }
    ]
}


class TestGetGamePitchingLines:
    @respx.mock
    async def test_extracts_two_pitchers_with_innings_conversion(self) -> None:
        respx.get("https://statsapi.mlb.com/api/v1/game/12345/boxscore").mock(
            return_value=httpx.Response(200, json=_FAKE_BOXSCORE)
        )
        async with MLBClient() as mlb:
            lines = await mlb.get_game_pitching_lines(12345)

        assert len(lines) == 2
        cole = next(l for l in lines if l["player_name"] == "Gerrit Cole")  # noqa: E741
        assert cole["innings_pitched"] == pytest.approx(7.333, abs=0.001)
        assert cole["hits_allowed"] == 4
        assert cole["earned_runs"] == 1
        assert cole["walks_allowed"] == 2
        assert cole["strikeouts"] == 9
        assert cole["era"] == 2.85
        assert cole["whip"] == 0.93
        assert cole["throws"] == "R"
        assert cole["team"] == "New York Yankees"


class TestGetProbablePitchers:
    @respx.mock
    async def test_extracts_probable_pitchers(self) -> None:
        respx.get(url__regex=r"https://statsapi\.mlb\.com/api/v1/schedule.*").mock(
            return_value=httpx.Response(200, json=_FAKE_SCHEDULE_WITH_PROBABLES)
        )
        async with MLBClient() as mlb:
            probables = await mlb.get_probable_pitchers(date(2026, 5, 25))

        assert len(probables) == 2

        named = next(p for p in probables if p["game_id"] == 778901)
        assert named["home_pitcher_name"] == "Gerrit Cole"
        assert named["home_pitcher_id"] == 592789
        assert named["away_pitcher_name"] == "Brayan Bello"
        assert named["away_pitcher_id"] == 657241

        none_yet = next(p for p in probables if p["game_id"] == 778902)
        assert none_yet["home_pitcher_id"] is None
        assert none_yet["away_pitcher_id"] is None


class TestGetPlayerHandedness:
    @respx.mock
    async def test_extracts_bats_and_throws(self) -> None:
        respx.get("https://statsapi.mlb.com/api/v1/people/592789").mock(
            return_value=httpx.Response(
                200,
                json={
                    "people": [
                        {
                            "id": 592789,
                            "fullName": "Gerrit Cole",
                            "currentTeam": {"id": 147, "name": "New York Yankees"},
                            "primaryPosition": {"abbreviation": "P"},
                            "batSide": {"code": "R"},
                            "pitchHand": {"code": "R"},
                        }
                    ]
                },
            )
        )
        async with MLBClient() as mlb:
            info = await mlb.get_player(592789)
        assert info is not None
        assert info["bats"] == "R"
        assert info["throws"] == "R"


# ── ETL roundtrip ────────────────────────────────────────────────────────────


def _make_line(
    mlb_id: int, name: str, ip: float, hits: int, er: int, bb: int, k: int, throws: str = "R"
) -> PitchingLineInfo:
    return PitchingLineInfo(
        player_id=mlb_id,
        player_name=name,
        team="Yankees",
        team_id=147,
        innings_pitched=ip,
        hits_allowed=hits,
        earned_runs=er,
        walks_allowed=bb,
        strikeouts=k,
        era=None,
        whip=None,
        throws=throws,
    )


class TestPitcherEtlUpsert:
    async def test_upsert_creates_then_updates(self) -> None:
        async with TestSessionLocal() as session:
            game = Game(
                mlb_game_id=99201,
                date=date(2026, 5, 22),
                home_team="Yankees",
                away_team="Red Sox",
                status="Final",
            )
            session.add(game)
            await session.flush()

            line = _make_line(700001, "New Ace", ip=7.0, hits=5, er=2, bb=1, k=10)
            pid = await _upsert_pitcher_player(session, line)
            action = await _upsert_pitcher_game_stats(session, pid, game.id, 2026, line)
            assert action == "inserted"

            # Update with new stats — should overwrite the per-game row in place
            line2 = _make_line(700001, "New Ace", ip=7.0, hits=5, er=3, bb=1, k=10)
            action2 = await _upsert_pitcher_game_stats(session, pid, game.id, 2026, line2)
            assert action2 == "updated"

            await session.commit()

            rows = (
                await session.execute(
                    PitcherStats.__table__.select().where(
                        PitcherStats.player_id == pid
                    )
                )
            ).all()
            assert len(rows) == 1  # the update did NOT create a duplicate
            assert rows[0].earned_runs == 3


class TestSeasonAggregateRecalc:
    async def test_aggregates_per_game_into_season_row(self) -> None:
        async with TestSessionLocal() as session:
            game_a = Game(
                mlb_game_id=99301,
                date=date(2026, 5, 1),
                home_team="Yankees",
                away_team="Red Sox",
                status="Final",
            )
            game_b = Game(
                mlb_game_id=99302,
                date=date(2026, 5, 8),
                home_team="Yankees",
                away_team="Red Sox",
                status="Final",
            )
            session.add_all([game_a, game_b])
            await session.flush()

            line_a = _make_line(700002, "Two-Start Ace", ip=6.0, hits=4, er=2, bb=1, k=8)
            pid = await _upsert_pitcher_player(session, line_a)
            await _upsert_pitcher_game_stats(session, pid, game_a.id, 2026, line_a)

            line_b = _make_line(700002, "Two-Start Ace", ip=7.0, hits=3, er=1, bb=2, k=9)
            await _upsert_pitcher_game_stats(session, pid, game_b.id, 2026, line_b)
            await session.commit()

            written = await recalc_season_pitching_aggregates(session, 2026)
            assert written == 1
            await session.commit()

            agg = (
                await session.execute(
                    PitcherStats.__table__.select().where(
                        PitcherStats.player_id == pid,
                        PitcherStats.is_season_aggregate.is_(True),
                    )
                )
            ).one()
            # Totals: 13 IP, 7 H, 3 ER, 3 BB, 17 K
            assert agg.innings_pitched == pytest.approx(13.0)
            assert agg.hits_allowed == 7
            assert agg.earned_runs == 3
            assert agg.walks_allowed == 3
            assert agg.strikeouts == 17
            # ERA = (3*9)/13 = 2.077; WHIP = (3+7)/13 = 0.769
            assert agg.era == pytest.approx(2.08, abs=0.01)
            assert agg.whip == pytest.approx(0.77, abs=0.01)
            assert agg.games == 2

    async def test_recalc_idempotent(self) -> None:
        async with TestSessionLocal() as session:
            game = Game(
                mlb_game_id=99401,
                date=date(2026, 5, 15),
                home_team="A",
                away_team="B",
                status="Final",
            )
            session.add(game)
            await session.flush()
            line = _make_line(700003, "Idem Ace", ip=5.0, hits=2, er=1, bb=0, k=6)
            pid = await _upsert_pitcher_player(session, line)
            await _upsert_pitcher_game_stats(session, pid, game.id, 2026, line)
            await session.commit()

            await recalc_season_pitching_aggregates(session, 2026)
            await session.commit()
            await recalc_season_pitching_aggregates(session, 2026)
            await session.commit()

            agg_count = (
                await session.execute(
                    PitcherStats.__table__.select().where(
                        PitcherStats.player_id == pid,
                        PitcherStats.is_season_aggregate.is_(True),
                    )
                )
            ).all()
            assert len(agg_count) == 1  # second call updated, didn't create


class TestUpsertProbablePitchers:
    @respx.mock
    async def test_writes_pitcher_ids_to_game(self) -> None:
        # Need local Player rows for the MLB IDs in the fake schedule
        async with TestSessionLocal() as session:
            session.add_all(
                [
                    Player(mlb_id=592789, full_name="Gerrit Cole", team="Yankees", position="P"),
                    Player(mlb_id=657241, full_name="Brayan Bello", team="Red Sox", position="P"),
                ]
            )
            game = Game(
                mlb_game_id=778901,
                date=date(2026, 5, 25),
                home_team="New York Yankees",
                away_team="Boston Red Sox",
                status="Scheduled",
            )
            session.add(game)
            await session.commit()
            game_id = game.id

        respx.get(url__regex=r"https://statsapi\.mlb\.com/api/v1/schedule.*").mock(
            return_value=httpx.Response(200, json=_FAKE_SCHEDULE_WITH_PROBABLES)
        )

        async with TestSessionLocal() as session, MLBClient() as mlb:
            updated = await upsert_probable_pitchers(session, mlb, date(2026, 5, 25))
            await session.commit()

        assert updated == 1  # the second game in the fake response has no probable pitchers

        async with TestSessionLocal() as session:
            refreshed = await session.get(Game, game_id)
            assert refreshed.home_probable_pitcher_id is not None
            assert refreshed.away_probable_pitcher_id is not None
            home = await session.get(Player, refreshed.home_probable_pitcher_id)
            assert home.full_name == "Gerrit Cole"


# ── Schema partial-uniqueness coexistence ────────────────────────────────────


class TestSchemaPartialUniqueness:
    async def test_per_game_and_season_rows_coexist(self) -> None:
        async with TestSessionLocal() as session:
            session.add(
                Player(mlb_id=799001, full_name="Mr. Co-exist", team="X", position="P")
            )
            await session.flush()
            pid = (
                await session.execute(
                    Player.__table__.select().where(Player.mlb_id == 799001)
                )
            ).one().id

            game = Game(
                mlb_game_id=799101,
                date=date(2026, 5, 20),
                home_team="X",
                away_team="Y",
                status="Final",
            )
            session.add(game)
            await session.flush()

            # Per-game row
            session.add(
                PitcherStats(
                    player_id=pid,
                    game_id=game.id,
                    season=2026,
                    is_season_aggregate=False,
                    games=1,
                    innings_pitched=5.0,
                    hits_allowed=2,
                    earned_runs=1,
                    walks_allowed=0,
                    strikeouts=5,
                )
            )
            # Season aggregate row — same player, same season, no conflict
            session.add(
                PitcherStats(
                    player_id=pid,
                    game_id=None,
                    season=2026,
                    is_season_aggregate=True,
                    games=1,
                    innings_pitched=5.0,
                    hits_allowed=2,
                    earned_runs=1,
                    walks_allowed=0,
                    strikeouts=5,
                    era=1.80,
                    whip=0.40,
                )
            )
            await session.commit()
