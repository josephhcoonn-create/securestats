"""
Pydantic response shapes for the /picks endpoints — daily high-confidence
hit projections built on top of the enhanced hit-probability model.
"""
from datetime import date as _date

from pydantic import BaseModel, Field

from app.schemas.odds import BookmakerSnapshot
from app.schemas.stats import (
    EnhancedHitProbabilityResponse,
    EnhancedHitProbFactors,
)


class PickEntry(BaseModel):
    """One daily pick with full factor breakdown + the latest odds for
    the game the player is playing in (one BookmakerSnapshot per book)."""
    player_id: int
    player_name: str
    team: str
    opponent: str
    game_id: int
    probability: float
    display_probability: str
    confidence: int
    pitcher_name: str | None = None
    factors: EnhancedHitProbFactors
    odds: dict[str, BookmakerSnapshot] = Field(
        default_factory=dict,
        description="Latest odds for this pick's game, keyed by sportsbook",
    )


class PicksTodayResponse(BaseModel):
    target_date: _date
    min_probability: float
    min_confidence: int
    games_considered: int
    candidates_evaluated: int
    pick_count: int
    picks: list[PickEntry]


class PickPlayerResponse(EnhancedHitProbabilityResponse):
    """Reuses the enhanced-hit-prob envelope; the route resolves the
    next game + probable pitcher automatically before calling the model."""

    game_date: _date | None = Field(None, description="Date of the resolved game")
    opponent: str | None = Field(None, description="Opposing team for the resolved game")


class PickHistoryEntry(BaseModel):
    target_date: _date
    pick_count: int
    hits: int
    plate_appearances: int = Field(
        ..., description="Total AB for picked players across this date's games"
    )
    accuracy_pct: float | None = Field(
        None,
        description="hits / pick_count as a percent. None when pick_count is 0.",
    )


class PickHistoryResponse(BaseModel):
    days: int
    total_picks: int
    total_hits: int
    overall_accuracy_pct: float | None
    by_date: list[PickHistoryEntry]
