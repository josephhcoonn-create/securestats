"""
Player endpoints.

All endpoints require at minimum the 'viewer' role.

Route order matters: /search must be declared before /{id} so that the
literal string "search" is never mis-parsed as an integer player id.
"""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import TokenPayload, require_role
from app.database import get_db
from app.models.batting_stats import BattingStats
from app.models.game import Game
from app.models.player import Player
from app.models.user import UserRole
from app.schemas.players import (
    CareerStats,
    GameStatLine,
    PlayerDetail,
    PlayerListResponse,
    PlayerStatsResponse,
    PlayerSummary,
)

router = APIRouter(prefix="/players", tags=["players"])

# Shared dependency: any authenticated viewer or above
_viewer = Depends(require_role(UserRole.viewer))

# Column names the client is allowed to sort by
_PLAYER_SORT_FIELDS: dict[str, object] = {
    "full_name": Player.full_name,
    "team": Player.team,
    "position": Player.position,
    "mlb_id": Player.mlb_id,
}

_STATS_SORT_FIELDS: dict[str, object] = {
    "date": Game.date,
    "at_bats": BattingStats.at_bats,
    "hits": BattingStats.hits,
    "home_runs": BattingStats.home_runs,
    "rbis": BattingStats.rbis,
    "batting_avg": BattingStats.batting_avg,
}


# ── 1. Search players by name  (must precede /{id}) ──────────────────────────


@router.get(
    "/search",
    response_model=PlayerListResponse,
    summary="Search players by name (partial, case-insensitive)",
)
async def search_players(
    q: Annotated[str, Query(min_length=1, description="Partial player name")],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    _: TokenPayload = _viewer,
    db: AsyncSession = Depends(get_db),
) -> PlayerListResponse:
    pattern = f"%{q}%"
    base = Player.full_name.ilike(pattern)

    total: int = (
        await db.execute(select(func.count(Player.id)).where(base))
    ).scalar_one()

    rows = (
        await db.execute(
            select(Player)
            .where(base)
            .order_by(Player.full_name)
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()

    return PlayerListResponse(
        items=[PlayerSummary.model_validate(p) for p in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


# ── 2. List players ───────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=PlayerListResponse,
    summary="List all players (paginated, filterable by team / position)",
)
async def list_players(
    team: Annotated[str | None, Query(description="Filter by team name (partial)")] = None,
    position: Annotated[str | None, Query(description="Filter by position (partial)")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort_by: Annotated[
        Literal["full_name", "team", "position", "mlb_id"],
        Query(description="Field to sort by"),
    ] = "full_name",
    sort_order: Annotated[Literal["asc", "desc"], Query()] = "asc",
    _: TokenPayload = _viewer,
    db: AsyncSession = Depends(get_db),
) -> PlayerListResponse:
    filters = []
    if team:
        filters.append(Player.team.ilike(f"%{team}%"))
    if position:
        filters.append(Player.position.ilike(f"%{position}%"))

    count_q = select(func.count(Player.id))
    list_q = select(Player)
    if filters:
        count_q = count_q.where(*filters)
        list_q = list_q.where(*filters)

    total: int = (await db.execute(count_q)).scalar_one()

    col = _PLAYER_SORT_FIELDS[sort_by]
    order = col.asc() if sort_order == "asc" else col.desc()  # type: ignore[union-attr]
    rows = (
        await db.execute(list_q.order_by(order).limit(limit).offset(offset))
    ).scalars().all()

    return PlayerListResponse(
        items=[PlayerSummary.model_validate(p) for p in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


# ── 3. Single player with career stats ───────────────────────────────────────


@router.get(
    "/{player_id}",
    response_model=PlayerDetail,
    summary="Single player with career batting aggregates",
)
async def get_player(
    player_id: int,
    _: TokenPayload = _viewer,
    db: AsyncSession = Depends(get_db),
) -> PlayerDetail:
    player = await db.get(Player, player_id)
    if player is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")

    # Aggregate career stats in one query
    agg = (
        await db.execute(
            select(
                func.count(BattingStats.id).label("games_played"),
                func.coalesce(func.sum(BattingStats.at_bats), 0).label("total_at_bats"),
                func.coalesce(func.sum(BattingStats.hits), 0).label("total_hits"),
                func.coalesce(func.sum(BattingStats.home_runs), 0).label("total_home_runs"),
                func.coalesce(func.sum(BattingStats.rbis), 0).label("total_rbis"),
                func.avg(BattingStats.on_base_pct).label("career_obp"),
                func.avg(BattingStats.slugging_pct).label("career_slg"),
            ).where(BattingStats.player_id == player_id)
        )
    ).one()

    total_ab: int = agg.total_at_bats or 0
    total_hits: int = agg.total_hits or 0
    career_avg = round(total_hits / total_ab, 3) if total_ab > 0 else None
    career_obp = round(float(agg.career_obp), 3) if agg.career_obp is not None else None
    career_slg = round(float(agg.career_slg), 3) if agg.career_slg is not None else None

    return PlayerDetail(
        id=player.id,
        mlb_id=player.mlb_id,
        full_name=player.full_name,
        team=player.team,
        position=player.position,
        updated_at=player.updated_at,
        career_stats=CareerStats(
            games_played=agg.games_played,
            total_at_bats=total_ab,
            total_hits=total_hits,
            total_home_runs=agg.total_home_runs or 0,
            total_rbis=agg.total_rbis or 0,
            career_batting_avg=career_avg,
            career_obp=career_obp,
            career_slg=career_slg,
        ),
    )


# ── 4. Player game-by-game stats ──────────────────────────────────────────────


@router.get(
    "/{player_id}/stats",
    response_model=PlayerStatsResponse,
    summary="Player's game-by-game batting stats (paginated, filterable by date range)",
)
async def get_player_stats(
    player_id: int,
    from_date: Annotated[date | None, Query(description="Earliest game date (inclusive)")] = None,
    to_date: Annotated[date | None, Query(description="Latest game date (inclusive)")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort_by: Annotated[
        Literal["date", "at_bats", "hits", "home_runs", "rbis", "batting_avg"],
        Query(),
    ] = "date",
    sort_order: Annotated[Literal["asc", "desc"], Query()] = "desc",
    _: TokenPayload = _viewer,
    db: AsyncSession = Depends(get_db),
) -> PlayerStatsResponse:
    player = await db.get(Player, player_id)
    if player is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")

    # Build date filters once, reuse for both count and list queries
    date_filters = []
    if from_date:
        date_filters.append(Game.date >= from_date)
    if to_date:
        date_filters.append(Game.date <= to_date)

    # Base join: batting_stats ⟶ games
    base = (
        select(BattingStats, Game)
        .join(Game, BattingStats.game_id == Game.id)
        .where(BattingStats.player_id == player_id)
        .where(*date_filters)
    )

    total: int = (
        await db.execute(
            select(func.count(BattingStats.id))
            .join(Game, BattingStats.game_id == Game.id)
            .where(BattingStats.player_id == player_id)
            .where(*date_filters)
        )
    ).scalar_one()

    col = _STATS_SORT_FIELDS[sort_by]
    order = col.asc() if sort_order == "asc" else col.desc()  # type: ignore[union-attr]
    rows = (
        await db.execute(base.order_by(order).limit(limit).offset(offset))
    ).all()

    stat_lines: list[GameStatLine] = [
        GameStatLine(
            stat_id=bs.id,
            game_id=g.id,
            mlb_game_id=g.mlb_game_id,
            game_date=g.date,
            home_team=g.home_team,
            away_team=g.away_team,
            home_score=g.home_score,
            away_score=g.away_score,
            game_status=g.status,
            at_bats=bs.at_bats,
            hits=bs.hits,
            home_runs=bs.home_runs,
            rbis=bs.rbis,
            batting_avg=bs.batting_avg,
            on_base_pct=bs.on_base_pct,
            slugging_pct=bs.slugging_pct,
        )
        for bs, g in rows
    ]

    return PlayerStatsResponse(
        player=PlayerSummary.model_validate(player),
        items=stat_lines,
        total=total,
        limit=limit,
        offset=offset,
    )
