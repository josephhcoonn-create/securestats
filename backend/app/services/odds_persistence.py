"""
Odds persistence — bridges :mod:`app.services.odds_client` (HTTP) to
the :class:`GameOdds` table.

Public surface
--------------
- :func:`refresh_odds_for_date` — one-shot fetch + parse + match + insert
- :func:`get_latest_odds_for_games` — read latest snapshot per game/book
- :func:`get_odds_history_for_game` — every snapshot for one game, newest first

The persistence layer is intentionally separate from the HTTP client so
unit tests can exercise it against seeded GameOdds rows without burning
quota against the real API.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.game import Game
from app.models.odds import GameOdds
from app.services.odds_client import (
    OddsClient,
    match_odds_to_games,
    parse_odds_response,
)

logger = logging.getLogger(__name__)


@dataclass
class OddsRefreshResult:
    """
    Returned by :func:`refresh_odds_for_date` so callers (admin endpoint,
    scheduler) can surface quota burn without re-instantiating the client.
    """
    rows_inserted: int
    quota_remaining: int | None
    quota_used: int | None

    # Backward-compat: bool(result) and int(result) collapse to rows_inserted
    # so older code that did `if refresh_odds_for_date(...)` still works.
    def __bool__(self) -> bool:
        return self.rows_inserted > 0

    def __int__(self) -> int:
        return self.rows_inserted


async def refresh_odds_for_date(
    session: AsyncSession,
    api_key: str,
    target_date: _date | None = None,
) -> OddsRefreshResult:
    """
    Fetch + parse + match + UPSERT today's odds for every matched Game.

    Returns the count of inserted rows alongside the quota headers from
    the upstream response so callers can log / surface them. The unique
    constraint on ``(game_id, sportsbook, fetched_at)`` means re-running
    within the same minute is a no-op on existing rows.

    Raises:
      OddsApiError / OddsQuotaExhausted if the upstream call fails — the
      caller decides whether to swallow or surface.
    """
    when = target_date or _date.today()
    async with OddsClient(api_key=api_key) as oc:
        raw = await oc.get_todays_odds()
        remaining = oc.last_remaining_quota
        used = oc.last_used_quota
    logger.info(
        "refresh_odds_for_date(%s): %d games returned, quota remaining=%s used=%s",
        when,
        len(raw),
        remaining,
        used,
    )

    flat_rows = parse_odds_response(raw)
    if not flat_rows:
        return OddsRefreshResult(
            rows_inserted=0, quota_remaining=remaining, quota_used=used
        )

    matched = await match_odds_to_games(session, flat_rows)
    if not matched:
        return OddsRefreshResult(
            rows_inserted=0, quota_remaining=remaining, quota_used=used
        )

    inserted = 0
    for row, game_id in matched:
        # ON CONFLICT DO NOTHING + RETURNING gives us a reliable signal:
        # rows that actually inserted show up in the result, rows that
        # conflicted on the unique constraint don't.
        stmt = (
            pg_insert(GameOdds)
            .values(
                game_id=game_id,
                sportsbook=row["sportsbook"],
                home_moneyline=row["home_moneyline"],
                away_moneyline=row["away_moneyline"],
                spread_home=row["spread_home"],
                spread_away=row["spread_away"],
                over_under=row["over_under"],
                fetched_at=row["fetched_at"],
            )
            .on_conflict_do_nothing(constraint="uq_game_odds_game_book_fetched")
            .returning(GameOdds.id)
        )
        result = await session.execute(stmt)
        if result.scalar_one_or_none() is not None:
            inserted += 1

    await session.commit()
    logger.info(
        "refresh_odds_for_date(%s): %d rows inserted; quota remaining=%s used=%s",
        when, inserted, remaining, used,
    )
    return OddsRefreshResult(
        rows_inserted=inserted, quota_remaining=remaining, quota_used=used
    )


async def get_latest_odds_for_games(
    session: AsyncSession,
    game_ids: list[int],
) -> dict[int, list[GameOdds]]:
    """
    For each game_id, return the most recent snapshot per sportsbook
    (newest fetched_at). Returns ``{game_id: [GameOdds, ...]}``.

    Empty input returns an empty dict so callers can iterate safely.
    """
    if not game_ids:
        return {}

    # Pull every odds row for those games, then collapse to latest per book
    rows = (
        await session.execute(
            select(GameOdds)
            .where(GameOdds.game_id.in_(game_ids))
            .order_by(GameOdds.game_id, GameOdds.sportsbook, GameOdds.fetched_at.desc())
        )
    ).scalars().all()

    latest: dict[int, dict[str, GameOdds]] = {}
    for row in rows:
        by_book = latest.setdefault(row.game_id, {})
        if row.sportsbook not in by_book:
            by_book[row.sportsbook] = row  # first occurrence is the latest

    return {gid: list(books.values()) for gid, books in latest.items()}


async def get_odds_history_for_game(
    session: AsyncSession, game_id: int
) -> tuple[Game | None, list[GameOdds]]:
    """
    Return (game, [GameOdds rows newest first]) for one game.
    Game is None if not found; rows is [] if no odds captured.
    """
    game = await session.get(Game, game_id)
    if game is None:
        return None, []

    rows = (
        await session.execute(
            select(GameOdds)
            .where(GameOdds.game_id == game_id)
            .order_by(GameOdds.fetched_at.desc(), GameOdds.sportsbook)
        )
    ).scalars().all()
    return game, list(rows)


async def date_has_odds(session: AsyncSession, target_date: _date) -> bool:
    """
    True when there's at least one GameOdds row whose game falls on
    *target_date*. Used by /odds/today to decide whether a lazy refresh
    is warranted.
    """
    cnt = (
        await session.execute(
            select(GameOdds.id)
            .join(Game, GameOdds.game_id == Game.id)
            .where(Game.date == target_date)
            .limit(1)
        )
    ).first()
    return cnt is not None


__all__ = [
    "refresh_odds_for_date",
    "get_latest_odds_for_games",
    "get_odds_history_for_game",
    "date_has_odds",
]


# Re-export for convenience — callers can `from … import datetime` to
# stamp their own fetched_at values consistently with the parser.
_ = datetime  # noqa: F841 — keeps the import for symmetry with odds_client
