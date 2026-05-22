"""
Pydantic response schemas for the /games family of endpoints.
"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

# ── Boxscore line (one batter in a game) ─────────────────────────────────────


class BoxscoreLine(BaseModel):
    """A single player's batting stats within a game's boxscore."""

    stat_id: int = Field(..., description="PK of the batting_stats row")
    player_id: int = Field(..., description="DB PK of the player")
    mlb_id: int
    full_name: str
    team: str
    position: str
    at_bats: int
    hits: int
    home_runs: int
    rbis: int
    batting_avg: float | None
    on_base_pct: float | None
    slugging_pct: float | None


# ── Game shapes ───────────────────────────────────────────────────────────────


class GameSummary(BaseModel):
    """Flat game row — used in list responses and as a nested sub-object."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    mlb_game_id: int
    date: date
    home_team: str
    away_team: str
    home_score: int | None
    away_score: int | None
    status: str


class GameDetail(GameSummary):
    """Single-game detail — adds the full boxscore."""

    created_at: datetime
    boxscore: list[BoxscoreLine]


# ── Paginated response wrapper ────────────────────────────────────────────────


class GameListResponse(BaseModel):
    items: list[GameSummary]
    total: int
    limit: int
    offset: int
