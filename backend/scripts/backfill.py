"""
Backfill ETL for a historical date window.

Loops MLB games + box-score batting lines for every day in the window,
upserting players, games, and batting_stats. Reuses run_etl_for_date so
the per-day logic is identical to the daily scheduled job.

Examples
--------
    # Last 90 days (default)
    docker compose exec backend python scripts/backfill.py

    # Explicit window
    docker compose exec backend python scripts/backfill.py \
        --start 2026-03-01 --end 2026-05-22

    # Custom rolling window
    docker compose exec backend python scripts/backfill.py --days 30

Host-mode (outside Docker) on Windows: run from backend/ with
    $env:PYTHONPATH="."; python scripts/backfill.py --days 30
"""
import argparse
import asyncio
import logging
import selectors
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Make the script runnable from anywhere: ensure the backend/ root
# (parent of scripts/) is on sys.path so `from app...` resolves.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _parse_date(s: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            f"invalid date {s!r}; expected YYYY-MM-DD"
        ) from e


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Backfill ETL for a historical date window.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--start",
        type=_parse_date,
        help="Earliest date to load (YYYY-MM-DD). Defaults to end − --days.",
    )
    p.add_argument(
        "--end",
        type=_parse_date,
        default=date.today() - timedelta(days=1),
        help="Latest date to load (YYYY-MM-DD). Defaults to yesterday.",
    )
    p.add_argument(
        "--days",
        type=int,
        default=90,
        help="Rolling window size (ignored if --start is given).",
    )
    return p.parse_args()


async def main() -> int:
    args = _parse_args()
    end = args.end
    start = args.start or (end - timedelta(days=args.days - 1))

    if start > end:
        print(f"error: --start {start} is after --end {end}", file=sys.stderr)
        return 2

    # Imported lazily so --help works without DB env vars.
    from app.services.etl import backfill_date_range

    total_days = (end - start).days + 1
    print(f"Backfilling {total_days} day(s) from {start} to {end}…\n")
    started = datetime.now()

    results = await backfill_date_range(start, end)

    # Aggregate summary
    ok = sum(1 for r in results if r.success)
    games = sum(r.games_processed for r in results)
    players = sum(r.players_upserted for r in results)
    inserted = sum(r.stats_inserted for r in results)
    updated = sum(r.stats_updated for r in results)
    errors = sum(len(r.errors) for r in results)
    elapsed = (datetime.now() - started).total_seconds()

    print()
    print("=" * 64)
    print(f"  Backfill complete in {elapsed:.1f}s")
    print(f"  Days      : {ok}/{total_days} succeeded")
    print(f"  Games     : {games}")
    print(f"  Players   : {players} upserted")
    print(f"  Stat rows : {inserted} inserted, {updated} updated")
    print(f"  Errors    : {errors}")
    print("=" * 64)

    if errors:
        print("\nErrors:")
        for r in results:
            for err in r.errors:
                print(f"  {r.run_date}: {err}")

    return 0 if ok == total_days else 1


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s - %(message)s",
        datefmt="%H:%M:%S",
    )
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.exit(
            asyncio.run(
                main(),
                loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
            )
        )
    else:
        sys.exit(asyncio.run(main()))
