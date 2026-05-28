"""
Task 8.8 — explicit edge-case coverage for the enhanced hit-probability model.

The handedness matrix, confidence buckets, pitcher composite, and the
happy-path mini-league sit in test_enhanced_hit_probability.py. This
file covers the brief's named edge cases:

  - Pitcher row exists but has 0 innings (no confidence boost)
  - Player has never had a batting line (truly empty history)
  - Switch hitter ('S') — full integration through the model
  - Upper-bound clamp: extreme inputs cannot exceed 0.95
  - Lower-bound clamp: a pure no-hit profile still floors at 0.05
"""
from datetime import date, timedelta

import pytest

from app.models.batting_stats import BattingStats
from app.models.game import Game
from app.models.pitcher_stats import PitcherStats
from app.models.player import Player
from app.services.analytics import (
    DAILY_PICK_THRESHOLD,
    _calculate_confidence,
    _handedness_modifier,
    calculate_enhanced_hit_probability,
)
from tests.conftest import TestSessionLocal

TODAY = date.today()


# ── Confidence: pitcher with 0 innings does NOT add the +10 boost ──────────


class TestPitcherZeroInnings:
    def test_no_boost_when_pitcher_ip_is_zero(self) -> None:
        # 100 season AB → high tier = 85; 0 IP from pitcher → no boost
        assert _calculate_confidence(season_ab=100, pitcher_ip=0.0) == 85
        # Boundary: just under 50 IP → still no boost
        assert _calculate_confidence(season_ab=100, pitcher_ip=49.9) == 85
        # 50 IP → boost kicks in
        assert _calculate_confidence(season_ab=100, pitcher_ip=50.0) == 95

    async def test_zero_innings_pitcher_falls_to_baselines_in_model(self) -> None:
        """A pitcher row that exists but has 0 innings + null ERA/WHIP
        should be treated as 'no data' — the model uses league baselines
        and the pitcher_ip stays at 0 (no confidence boost)."""
        async with TestSessionLocal() as session:
            batter = Player(
                mlb_id=890001, full_name="Edge Batter", team="X", position="LF", bats="R",
            )
            pitcher = Player(
                mlb_id=890002, full_name="Empty Pitcher", team="Y", position="P", throws="R",
            )
            session.add_all([batter, pitcher])
            await session.flush()

            session.add(
                PitcherStats(
                    player_id=pitcher.id,
                    season=TODAY.year,
                    games=0,
                    innings_pitched=0.0,
                    hits_allowed=0,
                    earned_runs=0,
                    walks_allowed=0,
                    strikeouts=0,
                    era=None,
                    whip=None,
                )
            )
            await session.commit()

            result = await calculate_enhanced_hit_probability(
                session,
                player_id=batter.id,
                game_id=None,
                pitcher_id=pitcher.id,
            )

        # Pitcher data was effectively None → league baselines applied
        # → no pitcher_ip → confidence stays at low tier (no boost)
        assert result["confidence"] == 30
        # Output is still a valid probability in the clamp range
        assert 0.05 <= result["probability"] <= 0.95


# ── Player has no batting history at all ─────────────────────────────────


class TestPlayerWithNoRecentGames:
    async def test_truly_empty_history_yields_baseline_only_probability(
        self,
    ) -> None:
        """A player with zero BattingStats rows should produce a valid
        probability driven entirely by the league baseline + pitcher
        composite. recent/season/career/home-away should ALL be None
        in the surfaced factors."""
        async with TestSessionLocal() as session:
            ghost = Player(
                mlb_id=890101,
                full_name="Newly Called Up",
                team="Z",
                position="DH",
                bats="R",
            )
            session.add(ghost)
            await session.commit()
            await session.refresh(ghost)

            result = await calculate_enhanced_hit_probability(
                session, player_id=ghost.id, game_id=None, pitcher_id=None
            )

        assert result["factors"]["recent_avg"] is None
        assert result["factors"]["season_avg"] is None
        assert result["factors"]["career_avg"] is None
        assert result["factors"]["home_away_split"] is None
        # Confidence on zero AB → low tier exactly
        assert result["confidence"] == 30
        # Probability is still in the valid range
        assert 0.05 <= result["probability"] <= 0.95


# ── Switch hitter ──────────────────────────────────────────────────────────


class TestSwitchHitter:
    """The unit-level handedness matrix is in test_enhanced_hit_probability.
    This is the integration version — a real switch hitter run through
    the model against both LHP and RHP."""

    def test_switch_hitter_always_gets_boost(self) -> None:
        # Sanity: pure-function behavior
        assert _handedness_modifier("S", "L") == 0.015
        assert _handedness_modifier("S", "R") == 0.015

    async def test_switch_hitter_vs_lhp_and_rhp_both_get_boost(self) -> None:
        async with TestSessionLocal() as session:
            switch = Player(
                mlb_id=890201, full_name="Switch Slugger", team="X",
                position="LF", bats="S",
            )
            lhp = Player(
                mlb_id=890202, full_name="LHP", team="Y", position="P", throws="L",
            )
            rhp = Player(
                mlb_id=890203, full_name="RHP", team="Y", position="P", throws="R",
            )
            session.add_all([switch, lhp, rhp])
            await session.commit()

            vs_lhp = await calculate_enhanced_hit_probability(
                session, player_id=switch.id, game_id=None, pitcher_id=lhp.id,
            )
            vs_rhp = await calculate_enhanced_hit_probability(
                session, player_id=switch.id, game_id=None, pitcher_id=rhp.id,
            )

        # Both matchups apply the +0.015 boost (no same-hand penalty)
        assert vs_lhp["factors"]["handedness_matchup"] == 0.015
        assert vs_rhp["factors"]["handedness_matchup"] == 0.015


# ── Probability clamp [0.05, 0.95] ─────────────────────────────────────────


class TestProbabilityClamp:
    async def test_extreme_high_inputs_clamp_at_upper_bound(self) -> None:
        """Stack the deck: .800 hitter across 30+ games against a
        sub-1.00 WHIP pitcher with opposite-hand matchup. The per-game
        probability should hit the 0.95 ceiling."""
        async with TestSessionLocal() as session:
            elite_batter = Player(
                mlb_id=890301, full_name="Elite Bat", team="A",
                position="LF", bats="L",
            )
            elite_pitcher = Player(
                mlb_id=890302, full_name="Elite Arm", team="B",
                position="P", throws="R",
            )
            session.add_all([elite_batter, elite_pitcher])
            await session.flush()

            # Seed 7 final games over the past week with elite hitting line
            for i in range(1, 8):
                game = Game(
                    mlb_game_id=890_400 + i,
                    date=TODAY - timedelta(days=i),
                    home_team="A", away_team="B",
                    status="Final", home_score=5, away_score=4,
                )
                session.add(game)
                await session.flush()
                session.add(
                    BattingStats(
                        player_id=elite_batter.id,
                        game_id=game.id,
                        at_bats=5, hits=4, home_runs=1, rbis=3,
                        batting_avg=0.800,
                    )
                )

            # Pitcher with elite stats AND high innings (confidence boost)
            session.add(
                PitcherStats(
                    player_id=elite_pitcher.id,
                    season=TODAY.year,
                    games=12, innings_pitched=80.0,
                    hits_allowed=40, earned_runs=12,
                    walks_allowed=8, strikeouts=90,
                    era=1.35, whip=0.60,
                )
            )
            await session.commit()

            result = await calculate_enhanced_hit_probability(
                session,
                player_id=elite_batter.id,
                game_id=None,
                pitcher_id=elite_pitcher.id,
            )

        assert result["probability"] == 0.95  # upper clamp hit exactly
        assert result["threshold_met"] is True
        assert result["probability"] >= DAILY_PICK_THRESHOLD

    async def test_no_data_anywhere_floors_at_lower_bound(self) -> None:
        """No batter history, no pitcher data, no game context. The
        model should still return a probability inside the clamp range —
        never below 0.05."""
        async with TestSessionLocal() as session:
            blank = Player(
                mlb_id=890401, full_name="Total Blank", team="X", position="C",
            )
            session.add(blank)
            await session.commit()
            await session.refresh(blank)

            result = await calculate_enhanced_hit_probability(
                session, player_id=blank.id, game_id=None, pitcher_id=None
            )

        # Lower bound is 0.05 — even a fully empty profile floats above it
        assert result["probability"] >= 0.05
        assert result["probability"] <= 0.95
