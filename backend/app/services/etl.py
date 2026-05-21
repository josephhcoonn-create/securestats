"""
MLB Data ETL Pipeline
======================

Flow per date
─────────────
  EXTRACT  →  MLB Stats API (schedule + boxscores)
  TRANSFORM →  clean dicts → SQLAlchemy model values
  LOAD     →  PostgreSQL upserts inside savepoint-per-game transactions

Key design choices
──────────────────
- Each game is wrapped in a savepoint so a single bad game never
  rolls back an entire run.
- Players and Games are upserted (INSERT … ON CONFLICT DO UPDATE)
  so re-running the ETL is always safe / idempotent.
- BattingStats uses a select-then-update/insert pattern because
  SQLAlchemy's PostgreSQL upsert needs a unique constraint that
  requires a migration (deferred to a future phase).
- run_daily_etl()          — public entry point for the scheduler.
- backfill_date_range()    — bulk-loads historical data.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal
from app.models.batting_stats import BattingStats
from app.models.game import Game
from app.models.player import Player
from app.services.mlb_client import BattingStatsInfo, GameInfo, MLBClient

logger = logging.getLogger(__name__)

# ── Game statuses that have boxscore data worth ingesting ─────────────────────
PROCESSABLE_STATUSES: frozenset[str] = frozenset(
    {
        "In Progress",
        "Game Over",
        "Final",
        "Completed Early",
        "Manager challenge",
    }
)


# ── ETL result container ──────────────────────────────────────────────────────


@dataclass
class ETLResult:
    run_date: date
    games_processed: int = 0
    players_upserted: int = 0
    stats_inserted: int = 0
    stats_updated: int = 0
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def success(self) -> bool:
        return len(self.errors) == 0

    def summary(self) -> str:
        return (
            f"ETL {self.run_date}  games={self.games_processed}  "
            f"players={self.players_upserted}  "
            f"stats_new={self.stats_inserted}  stats_upd={self.stats_updated}  "
            f"errors={len(self.errors)}  {self.duration_seconds:.1f}s"
        )


# ── DB helpers ────────────────────────────────────────────────────────────────


async def _upsert_player(session: AsyncSession, line: BattingStatsInfo) -> int:
    """
    Upsert a Player row by ``mlb_id`` and return the DB primary key.

    If the player already exists, full_name / team / position are refreshed.
    """
    team = line["team"] or "Unknown"
    position = line["position"] or "N/A"

    stmt = pg_insert(Player).values(
        mlb_id=line["player_id"],
        full_name=line["player_name"],
        team=team,
        position=position,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["mlb_id"],
        set_={
            "full_name": stmt.excluded.full_name,
            "team": stmt.excluded.team,
            "position": stmt.excluded.position,
        },
    ).returning(Player.id)

    result = await session.execute(stmt)
    return result.scalar_one()


async def _upsert_game(session: AsyncSession, info: GameInfo) -> int:
    """
    Upsert a Game row by ``mlb_game_id`` and return the DB primary key.

    Scores and status are always refreshed so live-game re-runs stay current.
    """
    stmt = pg_insert(Game).values(
        mlb_game_id=info["game_id"],
        date=info["date"],
        home_team=info["home_team"],
        away_team=info["away_team"],
        home_score=info["home_score"],
        away_score=info["away_score"],
        status=info["status"],
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["mlb_game_id"],
        set_={
            "home_score": stmt.excluded.home_score,
            "away_score": stmt.excluded.away_score,
            "status": stmt.excluded.status,
        },
    ).returning(Game.id)

    result = await session.execute(stmt)
    return result.scalar_one()


async def _upsert_batting_stats(
    session: AsyncSession,
    player_db_id: int,
    game_db_id: int,
    line: BattingStatsInfo,
) -> str:
    """
    Insert or update a BattingStats row for (player_db_id, game_db_id).

    Returns ``"inserted"`` or ``"updated"`` so the caller can track counts.
    """
    result = await session.execute(
        select(BattingStats).where(
            BattingStats.player_id == player_db_id,
            BattingStats.game_id == game_db_id,
        )
    )
    existing: BattingStats | None = result.scalar_one_or_none()

    if existing:
        existing.at_bats = line["at_bats"]
        existing.hits = line["hits"]
        existing.home_runs = line["home_runs"]
        existing.rbis = line["rbis"]
        existing.batting_avg = line["batting_avg"]
        existing.on_base_pct = line["on_base_pct"]
        existing.slugging_pct = line["slugging_pct"]
        return "updated"
    else:
        session.add(
            BattingStats(
                player_id=player_db_id,
                game_id=game_db_id,
                at_bats=line["at_bats"],
                hits=line["hits"],
                home_runs=line["home_runs"],
                rbis=line["rbis"],
                batting_avg=line["batting_avg"],
                on_base_pct=line["on_base_pct"],
                slugging_pct=line["slugging_pct"],
            )
        )
        return "inserted"


# ── Core pipeline ─────────────────────────────────────────────────────────────


async def _process_game(
    session: AsyncSession,
    mlb: MLBClient,
    game_info: GameInfo,
    result: ETLResult,
) -> None:
    """
    Process a single game inside a savepoint.

    Failures roll back only this game's writes; outer transaction stays open.
    """
    game_id = game_info["game_id"]
    logger.info("Processing game %d — %s @ %s [%s]",
                game_id, game_info["away_team"], game_info["home_team"], game_info["status"])

    async with session.begin_nested():  # savepoint
        # Upsert game record
        game_db_id = await _upsert_game(session, game_info)

        # Fetch boxscore
        batting_lines = await mlb.get_game_boxscore(game_id)
        if not batting_lines:
            logger.info("  game %d: no batting lines (game may not have started)", game_id)
            return

        for line in batting_lines:
            try:
                player_db_id = await _upsert_player(session, line)
                result.players_upserted += 1

                action = await _upsert_batting_stats(session, player_db_id, game_db_id, line)
                if action == "inserted":
                    result.stats_inserted += 1
                else:
                    result.stats_updated += 1

            except Exception as exc:  # noqa: BLE001
                msg = f"game {game_id} player {line['player_id']}: {exc}"
                logger.warning("  stat error — %s", msg)
                result.errors.append(msg)

    result.games_processed += 1
    logger.info("  game %d done — %d lines", game_id, len(batting_lines))


async def run_etl_for_date(target_date: date) -> ETLResult:
    """
    Full ETL for a single calendar date.

    Fetches the schedule, filters for games with playable data, and
    processes each game inside its own DB savepoint.
    """
    result = ETLResult(run_date=target_date)
    start = time.monotonic()

    logger.info("═══ ETL START  date=%s ═══", target_date)

    try:
        async with MLBClient() as mlb, AsyncSessionLocal() as session:
            async with session.begin():
                # ── EXTRACT ──────────────────────────────────────────────────
                all_games = await mlb.get_todays_schedule(target_date)
                processable = [g for g in all_games if g["status"] in PROCESSABLE_STATUSES]

                logger.info(
                    "Schedule: %d total games, %d processable",
                    len(all_games),
                    len(processable),
                )

                if not processable:
                    logger.info("No processable games — ETL complete")
                    result.duration_seconds = time.monotonic() - start
                    return result

                # ── TRANSFORM + LOAD (per game) ───────────────────────────────
                for game_info in processable:
                    try:
                        await _process_game(session, mlb, game_info, result)
                    except Exception as exc:  # noqa: BLE001
                        msg = f"game {game_info['game_id']} failed: {exc}"
                        logger.error("  %s", msg)
                        result.errors.append(msg)

    except Exception as exc:  # noqa: BLE001
        msg = f"Pipeline-level failure: {exc}"
        logger.exception(msg)
        result.errors.append(msg)

    result.duration_seconds = time.monotonic() - start
    logger.info("═══ ETL END    %s ═══", result.summary())
    return result


# ── Public entry points ───────────────────────────────────────────────────────


async def run_daily_etl() -> ETLResult:
    """Run the ETL pipeline for today. Called by the APScheduler job."""
    return await run_etl_for_date(date.today())


async def backfill_date_range(
    start_date: date,
    end_date: date,
) -> list[ETLResult]:
    """
    Load historical data for every date in [start_date, end_date].

    Dates are processed sequentially to respect the MLB API rate limit.
    Returns one :class:`ETLResult` per date.
    """
    if start_date > end_date:
        raise ValueError(f"start_date {start_date} must be ≤ end_date {end_date}")

    total_days = (end_date - start_date).days + 1
    logger.info("Backfill: %d days from %s to %s", total_days, start_date, end_date)

    results: list[ETLResult] = []
    current = start_date

    while current <= end_date:
        logger.info("Backfill progress: %s (%d/%d)", current, len(results) + 1, total_days)
        result = await run_etl_for_date(current)
        results.append(result)
        current += timedelta(days=1)

    success_count = sum(1 for r in results if r.success)
    total_stats = sum(r.stats_inserted + r.stats_updated for r in results)
    logger.info(
        "Backfill complete: %d/%d days OK, %d total stat lines",
        success_count,
        total_days,
        total_stats,
    )
    return results
