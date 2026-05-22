"""
Game endpoints.

All endpoints require at minimum the 'viewer' role.

Route order matters: /today must be declared before /{id} so that the
literal string "today" is never mis-parsed as an integer game id.
"""

from datetime import date as date_type
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
from app.schemas.games import BoxscoreLine, GameDetail, GameListResponse, GameSummary

router = APIRouter(prefix="/games", tags=["games"])

# Shared dependency: any authenticated viewer or above
_viewer = Depends(require_role(UserRole.viewer))

# Column names the client is allowed to sort by
_GAME_SORT_FIELDS: dict[str, object] = {
    "date": Game.date,
    "home_team": Game.home_team,
    "away_team": Game.away_team,
    "status": Game.status,
}


# ── Helper: build boxscore for a game ────────────────────────────────────────


async def _fetch_boxscore(db: AsyncSession, game_id: int) -> list[BoxscoreLine]:
    rows = (
        await db.execute(
            select(BattingStats, Player)
            .join(Player, BattingStats.player_id == Player.id)
            .where(BattingStats.game_id == game_id)
            .order_by(Player.team, Player.full_name)
        )
    ).all()

    return [
        BoxscoreLine(
            stat_id=bs.id,
            player_id=p.id,
            mlb_id=p.mlb_id,
            full_name=p.full_name,
            team=p.team,
            position=p.position,
            at_bats=bs.at_bats,
            hits=bs.hits,
            home_runs=bs.home_runs,
            rbis=bs.rbis,
            batting_avg=bs.batting_avg,
            on_base_pct=bs.on_base_pct,
            slugging_pct=bs.slugging_pct,
        )
        for bs, p in rows
    ]


# ── 1. Today's schedule  (must precede /{id}) ─────────────────────────────────


@router.get(
    "/today",
    response_model=GameListResponse,
    summary="Today's schedule with live / final scores",
)
async def get_todays_games(
    _: TokenPayload = _viewer,
    db: AsyncSession = Depends(get_db),
) -> GameListResponse:
    today = date_type.today()
    rows = (
        await db.execute(
            select(Game)
            .where(Game.date == today)
            .order_by(Game.mlb_game_id)
        )
    ).scalars().all()

    return GameListResponse(
        items=[GameSummary.model_validate(g) for g in rows],
        total=len(rows),
        limit=len(rows),
        offset=0,
    )


# ── 2. List games ─────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=GameListResponse,
    summary="List games (paginated, filterable by date / team / status)",
)
async def list_games(
    game_date: Annotated[
        date_type | None,
        Query(alias="date", description="Filter by exact game date (YYYY-MM-DD)"),
    ] = None,
    from_date: Annotated[date_type | None, Query(description="Earliest date (inclusive)")] = None,
    to_date: Annotated[date_type | None, Query(description="Latest date (inclusive)")] = None,
    team: Annotated[
        str | None,
        Query(description="Filter by home or away team name (partial)"),
    ] = None,
    game_status: Annotated[
        str | None,
        Query(alias="status", description="Filter by game status (partial, e.g. 'Final')"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort_by: Annotated[
        Literal["date", "home_team", "away_team", "status"],
        Query(description="Field to sort by"),
    ] = "date",
    sort_order: Annotated[Literal["asc", "desc"], Query()] = "desc",
    _: TokenPayload = _viewer,
    db: AsyncSession = Depends(get_db),
) -> GameListResponse:
    filters = []

    if game_date:
        filters.append(Game.date == game_date)
    else:
        if from_date:
            filters.append(Game.date >= from_date)
        if to_date:
            filters.append(Game.date <= to_date)

    if team:
        filters.append(
            (Game.home_team.ilike(f"%{team}%")) | (Game.away_team.ilike(f"%{team}%"))
        )
    if game_status:
        filters.append(Game.status.ilike(f"%{game_status}%"))

    count_q = select(func.count(Game.id)).where(*filters)
    list_q = select(Game).where(*filters)

    total: int = (await db.execute(count_q)).scalar_one()

    col = _GAME_SORT_FIELDS[sort_by]
    order = col.asc() if sort_order == "asc" else col.desc()  # type: ignore[union-attr]
    rows = (
        await db.execute(list_q.order_by(order).limit(limit).offset(offset))
    ).scalars().all()

    return GameListResponse(
        items=[GameSummary.model_validate(g) for g in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


# ── 3. Single game with full boxscore ─────────────────────────────────────────


@router.get(
    "/{game_id}",
    response_model=GameDetail,
    summary="Single game with full boxscore",
)
async def get_game(
    game_id: int,
    _: TokenPayload = _viewer,
    db: AsyncSession = Depends(get_db),
) -> GameDetail:
    game = await db.get(Game, game_id)
    if game is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found")

    boxscore = await _fetch_boxscore(db, game_id)

    return GameDetail(
        id=game.id,
        mlb_game_id=game.mlb_game_id,
        date=game.date,
        home_team=game.home_team,
        away_team=game.away_team,
        home_score=game.home_score,
        away_score=game.away_score,
        status=game.status,
        created_at=game.created_at,
        boxscore=boxscore,
    )
