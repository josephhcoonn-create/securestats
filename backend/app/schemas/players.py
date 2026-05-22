"""
Pydantic response schemas for the /players family of endpoints.
"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

# ── Career aggregates ─────────────────────────────────────────────────────────


class CareerStats(BaseModel):
    """Season-to-date / career batting aggregates for a single player."""

    games_played: int = Field(..., description="Total games with a batting line")
    total_at_bats: int
    total_hits: int
    total_home_runs: int
    total_rbis: int
    career_batting_avg: float | None = Field(
        None, description="Hits ÷ at-bats across all loaded games"
    )
    career_obp: float | None = Field(
        None, description="Mean on-base percentage across games with an OBP value"
    )
    career_slg: float | None = Field(
        None, description="Mean slugging percentage across games with a SLG value"
    )


# ── Player shapes ─────────────────────────────────────────────────────────────


class PlayerSummary(BaseModel):
    """Flat player row — used in list responses and as a nested sub-object.

    The aggregate fields (games_played, career_batting_avg, career_home_runs,
    career_rbis) are populated by the list/search endpoints via a LEFT JOIN +
    GROUP BY on batting_stats. They're optional because nested usages
    (e.g. PlayerStatsResponse.player) build a summary from the bare ORM
    object and leave them None.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    mlb_id: int
    full_name: str
    team: str
    position: str

    # Career aggregates — optional, populated by list/search endpoints only
    games_played: int | None = None
    career_batting_avg: float | None = None
    career_home_runs: int | None = None
    career_rbis: int | None = None


class PlayerDetail(PlayerSummary):
    """Single-player detail — adds career stats and housekeeping timestamps."""

    updated_at: datetime
    career_stats: CareerStats


# ── Per-game stat line for a player ──────────────────────────────────────────


class GameStatLine(BaseModel):
    """One row in a player's game-by-game history."""

    stat_id: int = Field(..., description="PK of the batting_stats row")
    game_id: int = Field(..., description="DB PK of the game")
    mlb_game_id: int
    game_date: date
    home_team: str
    away_team: str
    home_score: int | None
    away_score: int | None
    game_status: str
    at_bats: int
    hits: int
    home_runs: int
    rbis: int
    batting_avg: float | None
    on_base_pct: float | None
    slugging_pct: float | None


# ── Paginated response wrappers ───────────────────────────────────────────────


class PlayerListResponse(BaseModel):
    items: list[PlayerSummary]
    total: int
    limit: int
    offset: int


class PlayerStatsResponse(BaseModel):
    player: PlayerSummary
    items: list[GameStatLine]
    total: int
    limit: int
    offset: int
