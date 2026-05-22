"""
Analytics / stats endpoints.

All endpoints require the 'analyst' role minimum.

Routes
──────
  GET  /stats/leaders          — top N players by any batting stat
  GET  /stats/teams            — teams ranked by aggregate batting stat
  GET  /stats/hit-probability/{player_id}
  GET  /stats/streaks          — hot / cold streaks
  POST /stats/compare          — side-by-side player comparison
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import TokenPayload, require_role
from app.database import get_db
from app.models.user import UserRole
from app.schemas.stats import (
    BattingLeadersResponse,
    HitProbabilityResponse,
    PlayerComparisonResponse,
    StreaksResponse,
    TeamRankingsResponse,
)
from app.services.analytics import (
    VALID_STATS,
    calculate_hit_probability,
    get_batting_leaders,
    get_hot_cold_streaks,
    get_player_comparison,
    get_team_rankings,
)

router = APIRouter(prefix="/stats", tags=["stats"])

# Shared dependency — analyst or above
_analyst = Depends(require_role(UserRole.analyst))


# ── Request body for the comparison endpoint ──────────────────────────────────


class CompareRequest(BaseModel):
    player_ids: list[int] = Field(
        ...,
        min_length=2,
        max_length=10,
        description="DB player IDs to compare (2–10 players)",
    )


# ── 1. Batting leaders ────────────────────────────────────────────────────────


@router.get(
    "/leaders",
    response_model=BattingLeadersResponse,
    summary="Top N players by batting stat (optionally over a rolling date window)",
)
async def batting_leaders(
    stat: Annotated[
        str,
        Query(description=f"Stat to rank by. One of: {sorted(VALID_STATS)}"),
    ] = "batting_avg",
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    days: Annotated[
        int | None,
        Query(ge=1, description="Rolling window in days; omit for all-time"),
    ] = None,
    _: TokenPayload = _analyst,
    db: AsyncSession = Depends(get_db),
) -> BattingLeadersResponse:
    return await get_batting_leaders(db, stat=stat, limit=limit, days=days)


# ── 2. Team rankings ──────────────────────────────────────────────────────────


@router.get(
    "/teams",
    response_model=TeamRankingsResponse,
    summary="Teams ranked by an aggregate batting stat",
)
async def team_rankings(
    stat: Annotated[
        str,
        Query(description=f"Stat to rank by. One of: {sorted(VALID_STATS)}"),
    ] = "home_runs",
    _: TokenPayload = _analyst,
    db: AsyncSession = Depends(get_db),
) -> TeamRankingsResponse:
    return await get_team_rankings(db, stat=stat)


# ── 3. Hit probability ────────────────────────────────────────────────────────


@router.get(
    "/hit-probability/{player_id}",
    response_model=HitProbabilityResponse,
    summary="Estimate hit probability for a player's next at-bat",
)
async def hit_probability(
    player_id: int,
    _: TokenPayload = _analyst,
    db: AsyncSession = Depends(get_db),
) -> HitProbabilityResponse:
    return await calculate_hit_probability(db, player_id=player_id)


# ── 4. Hot / cold streaks ─────────────────────────────────────────────────────


@router.get(
    "/streaks",
    response_model=StreaksResponse,
    summary="Players on hot (avg ≥ .350) or cold (avg ≤ .150) streaks",
)
async def streaks(
    type: Annotated[
        Literal["hot", "cold", "both"],
        Query(description="'hot', 'cold', or 'both'"),
    ] = "both",
    min_games: Annotated[
        int,
        Query(ge=3, le=30, description="Minimum games in the rolling window"),
    ] = 5,
    _: TokenPayload = _analyst,
    db: AsyncSession = Depends(get_db),
) -> StreaksResponse:
    return await get_hot_cold_streaks(db, streak_type=type, min_games=min_games)


# ── 5. Player comparison ──────────────────────────────────────────────────────


@router.post(
    "/compare",
    response_model=PlayerComparisonResponse,
    summary="Side-by-side career and recent-form comparison for 2–10 players",
)
async def compare_players(
    body: CompareRequest,
    _: TokenPayload = _analyst,
    db: AsyncSession = Depends(get_db),
) -> PlayerComparisonResponse:
    return await get_player_comparison(db, player_ids=body.player_ids)
