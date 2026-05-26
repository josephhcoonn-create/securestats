"""
Pydantic response shapes for the /odds endpoints.

Each game gets a flat header (game_id, teams, date, status) plus a
nested mapping of sportsbook → latest odds snapshot. /odds/game/{id}
returns every historical snapshot in newest-first order so clients
can visualize line movement.
"""
from datetime import date as _date
from datetime import datetime

from pydantic import BaseModel, Field


class BookmakerSnapshot(BaseModel):
    """One book's quote for one game at one point in time."""
    sportsbook: str
    home_moneyline: int | None
    away_moneyline: int | None
    spread_home: float | None
    spread_away: float | None
    over_under: float | None
    fetched_at: datetime


class GameWithOdds(BaseModel):
    """Game header + latest snapshot from each book."""
    game_id: int
    mlb_game_id: int
    date: _date
    home_team: str
    away_team: str
    status: str
    bookmakers: dict[str, BookmakerSnapshot] = Field(
        default_factory=dict,
        description="Maps sportsbook key (e.g. 'draftkings') → latest snapshot",
    )


class OddsTodayResponse(BaseModel):
    target_date: _date
    games_with_odds: int
    games_without_odds: int = Field(
        ..., description="Games scheduled on this date that no book has priced yet"
    )
    quota_remaining: int | None = Field(
        None,
        description="x-requests-remaining from The Odds API after the last refresh, or None if odds came from cache only",
    )
    games: list[GameWithOdds]


class OddsHistoryResponse(BaseModel):
    """Every snapshot for one game, newest first — for line-movement charts."""
    game_id: int
    mlb_game_id: int
    home_team: str
    away_team: str
    date: _date
    snapshot_count: int
    snapshots: list[BookmakerSnapshot]
