"""
Pydantic response schemas for the /stats analytics endpoints.

Every numeric stat has a parallel ``display_*`` field pre-formatted for
the frontend:
  • batting averages / OBP / SLG / OPS  →  ".302" or "1.023"
  • counting stats (HR, RBI, H)         →  "23"
  • probabilities                        →  "28.4%"
"""

from pydantic import BaseModel, Field

# ── Helpers ───────────────────────────────────────────────────────────────────


def fmt_avg(value: float | None) -> str:
    """Format a rate stat as '.302'. Returns '---' for None."""
    if value is None:
        return "---"
    formatted = f"{value:.3f}"
    # Strip leading '0' for values < 1.0: "0.302" → ".302"
    return formatted[1:] if value < 1.0 and formatted.startswith("0") else formatted


def fmt_int(value: int | float | None) -> str:
    """Format a counting stat as a plain integer string."""
    return "0" if value is None else str(int(value))


def fmt_pct(value: float | None) -> str:
    """Format a probability as '28.4%'. Returns '---' for None."""
    return "---" if value is None else f"{value * 100:.1f}%"


# ── Batting leaders ───────────────────────────────────────────────────────────


class LeaderEntry(BaseModel):
    rank: int
    player_id: int
    mlb_id: int
    full_name: str
    team: str
    position: str
    games_played: int
    at_bats: int
    value: float | None
    display_value: str = Field(..., description="Pre-formatted for UI display")


class BattingLeadersResponse(BaseModel):
    stat: str
    days: int | None = Field(None, description="Rolling window; None = all-time")
    min_at_bats: int
    leaders: list[LeaderEntry]


# ── Team rankings ─────────────────────────────────────────────────────────────


class TeamRankingEntry(BaseModel):
    rank: int
    team: str
    games_played: int
    at_bats: int
    value: float | None
    display_value: str


class TeamRankingsResponse(BaseModel):
    stat: str
    rankings: list[TeamRankingEntry]


# ── Hit probability ───────────────────────────────────────────────────────────


class HitProbabilityResponse(BaseModel):
    player_id: int
    mlb_id: int
    full_name: str
    team: str
    # Component averages
    recent_avg: float | None = Field(None, description="Last-30-game batting average")
    career_avg: float | None = Field(None, description="All-time batting average")
    league_avg: float = Field(..., description="League-wide batting average")
    # Estimate
    hit_probability: float
    display_probability: str
    ci_lower: float = Field(..., description="95% confidence interval lower bound")
    ci_upper: float = Field(..., description="95% confidence interval upper bound")
    display_ci: str = Field(..., description="'[22.1%, 34.7%]'")
    # Sample metadata
    recent_games: int
    recent_at_bats: int
    confidence: str = Field(
        ..., description="'low' | 'medium' | 'high' based on sample size"
    )


# ── Hot / cold streaks ────────────────────────────────────────────────────────


class StreakEntry(BaseModel):
    player_id: int
    mlb_id: int
    full_name: str
    team: str
    position: str
    streak_type: str = Field(..., description="'hot' or 'cold'")
    games: int = Field(..., description="Number of recent games in the window")
    hits: int
    at_bats: int
    period_avg: float | None
    display_avg: str


class StreaksResponse(BaseModel):
    streak_type: str = Field(..., description="'hot', 'cold', or 'both'")
    min_games: int
    hot_threshold: float = 0.350
    cold_threshold: float = 0.150
    streaks: list[StreakEntry]


# ── Player comparison ─────────────────────────────────────────────────────────


class ComparisonPlayerStats(BaseModel):
    player_id: int
    mlb_id: int
    full_name: str
    team: str
    position: str
    # Career totals
    games_played: int
    at_bats: int
    hits: int
    home_runs: int
    rbis: int
    batting_avg: float | None
    on_base_pct: float | None
    slugging_pct: float | None
    ops: float | None
    # Recent form (last 10 games)
    recent_games: int
    recent_avg: float | None
    # Display values
    display_avg: str
    display_ops: str
    display_recent_avg: str


class PlayerComparisonResponse(BaseModel):
    players: list[ComparisonPlayerStats]
    leaders: dict[str, int | None] = Field(
        ...,
        description="Maps stat name → player_id of the leader among compared players",
    )
