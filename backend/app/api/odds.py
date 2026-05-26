"""
/odds endpoints — viewer+ access.

  GET /odds/today           latest snapshot per book for every game today
  GET /odds/game/{game_id}  every snapshot ever captured for one game

`/odds/today` lazy-refreshes from The Odds API when the DB has no rows
for today AND a key is configured. Subsequent requests serve from the
DB so we don't burn quota on every page load.
"""
from datetime import date as _date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import TokenPayload, require_role
from app.config import settings
from app.database import get_db
from app.models.game import Game
from app.models.odds import GameOdds
from app.models.user import UserRole
from app.schemas.odds import (
    BookmakerSnapshot,
    GameWithOdds,
    OddsHistoryResponse,
    OddsTodayResponse,
)
from app.services.odds_client import OddsApiError, OddsQuotaExhausted
from app.services.odds_persistence import (
    date_has_odds,
    get_latest_odds_for_games,
    get_odds_history_for_game,
    refresh_odds_for_date,
)

router = APIRouter(prefix="/odds", tags=["odds"])
_viewer = Depends(require_role(UserRole.viewer))


def _to_snapshot(row: GameOdds) -> BookmakerSnapshot:
    return BookmakerSnapshot(
        sportsbook=row.sportsbook,
        home_moneyline=row.home_moneyline,
        away_moneyline=row.away_moneyline,
        spread_home=row.spread_home,
        spread_away=row.spread_away,
        over_under=row.over_under,
        fetched_at=row.fetched_at,
    )


# ── 1. /odds/today ───────────────────────────────────────────────────────────


@router.get(
    "/today",
    response_model=OddsTodayResponse,
    summary="Latest odds per book for every game on today's slate",
)
async def odds_today(
    _: Annotated[TokenPayload, _viewer],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OddsTodayResponse:
    today = _date.today()
    quota_remaining: int | None = None

    # Lazy refresh: only hit The Odds API when nothing's been captured
    # for today AND a key is configured. Free tier is 500/month — we
    # explicitly avoid burning it on every request.
    if not await date_has_odds(db, today) and settings.the_odds_api_key:
        try:
            await refresh_odds_for_date(db, settings.the_odds_api_key, today)
        except OddsQuotaExhausted:
            # Serve whatever cached rows exist; surface no fresh quota number
            pass
        except OddsApiError:
            # Don't block the dashboard on upstream errors — return [] gracefully
            pass

    games_today = (
        await db.execute(select(Game).where(Game.date == today).order_by(Game.id))
    ).scalars().all()
    if not games_today:
        return OddsTodayResponse(
            target_date=today,
            games_with_odds=0,
            games_without_odds=0,
            quota_remaining=quota_remaining,
            games=[],
        )

    latest = await get_latest_odds_for_games(db, [g.id for g in games_today])

    games_payload: list[GameWithOdds] = []
    games_with = games_without = 0
    for g in games_today:
        snapshots = latest.get(g.id, [])
        bookmakers = {s.sportsbook: _to_snapshot(s) for s in snapshots}
        if bookmakers:
            games_with += 1
        else:
            games_without += 1
        games_payload.append(
            GameWithOdds(
                game_id=g.id,
                mlb_game_id=g.mlb_game_id,
                date=g.date,
                home_team=g.home_team,
                away_team=g.away_team,
                status=g.status,
                bookmakers=bookmakers,
            )
        )

    return OddsTodayResponse(
        target_date=today,
        games_with_odds=games_with,
        games_without_odds=games_without,
        quota_remaining=quota_remaining,
        games=games_payload,
    )


# ── 2. /odds/game/{id} ───────────────────────────────────────────────────────


@router.get(
    "/game/{game_id}",
    response_model=OddsHistoryResponse,
    summary="Every odds snapshot ever captured for one game (newest first)",
)
async def odds_for_game(
    game_id: int,
    _: Annotated[TokenPayload, _viewer],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OddsHistoryResponse:
    game, rows = await get_odds_history_for_game(db, game_id)
    if game is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game {game_id} not found",
        )

    return OddsHistoryResponse(
        game_id=game.id,
        mlb_game_id=game.mlb_game_id,
        home_team=game.home_team,
        away_team=game.away_team,
        date=game.date,
        snapshot_count=len(rows),
        snapshots=[_to_snapshot(r) for r in rows],
    )
