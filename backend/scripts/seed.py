"""
Seed the database with three demo users and a week of real MLB data.

Idempotent: re-running won't create duplicate users or duplicate stat
rows (the ETL pipeline already upserts on natural keys).

Usage
-----
    docker compose exec backend python -m scripts.seed

Default credentials (CHANGE THESE in any non-local environment):
    admin    / admin123     → role=admin
    analyst  / analyst123   → role=analyst
    viewer   / viewer123    → role=viewer
"""
from __future__ import annotations

import asyncio
import logging
import selectors
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Make `from app...` work no matter how the script is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.auth.password import hash_password  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.services.etl import backfill_date_range  # noqa: E402

# ── Demo users ────────────────────────────────────────────────────────────────

DEMO_USERS = [
    ("admin",   "admin@securestats.local",   "Admin123!",   UserRole.admin),
    ("analyst", "analyst@securestats.local", "Analyst123!", UserRole.analyst),
    ("viewer",  "viewer@securestats.local",  "Viewer123!",  UserRole.viewer),
]

BACKFILL_DAYS = 7

logger = logging.getLogger("seed")


async def seed_users() -> tuple[int, int]:
    """Create demo users that don't already exist. Returns (created, existing)."""
    created = existing = 0

    async with AsyncSessionLocal() as session:
        for username, email, password, role in DEMO_USERS:
            stmt = select(User).where(User.username == username)
            if (await session.execute(stmt)).scalar_one_or_none() is not None:
                logger.info("user %-8s already exists — skipping", username)
                existing += 1
                continue

            session.add(
                User(
                    username=username,
                    email=email,
                    hashed_password=hash_password(password),
                    role=role,
                    is_active=True,
                )
            )
            created += 1
            logger.info("created user %-8s (role=%s)", username, role.value)

        await session.commit()

    return created, existing


async def seed_games() -> dict[str, int]:
    """Backfill the last week of MLB games. Returns an aggregate summary."""
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=BACKFILL_DAYS - 1)

    logger.info("backfilling %d days: %s → %s", BACKFILL_DAYS, start, end)
    results = await backfill_date_range(start, end)

    return {
        "days_ok": sum(1 for r in results if r.success),
        "days_total": len(results),
        "games": sum(r.games_processed for r in results),
        "players": sum(r.players_upserted for r in results),
        "inserted": sum(r.stats_inserted for r in results),
        "updated": sum(r.stats_updated for r in results),
        "errors": sum(len(r.errors) for r in results),
    }


def _print_summary(
    user_created: int, user_existing: int, eta: dict[str, int], elapsed: float
) -> None:
    print()
    print("=" * 64)
    print(f"  SecureStats seed complete in {elapsed:.1f}s")
    print("-" * 64)
    print(f"  Users    : {user_created} created, {user_existing} already present")
    print(f"  Days     : {eta['days_ok']}/{eta['days_total']} backfilled")
    print(f"  Games    : {eta['games']} processed")
    print(f"  Players  : {eta['players']} upserted")
    print(f"  Stats    : {eta['inserted']} inserted, {eta['updated']} updated")
    print(f"  Errors   : {eta['errors']}")
    print("=" * 64)
    if user_created:
        print()
        print("  Demo credentials (CHANGE THESE in non-local environments):")
        for username, _email, password, role in DEMO_USERS:
            print(f"    {username:<8} / {password:<12}  → {role.value}")
        print()


async def main() -> int:
    started = datetime.now()

    print("Seeding users…")
    user_created, user_existing = await seed_users()

    print("Backfilling MLB data…")
    eta = await seed_games()

    _print_summary(user_created, user_existing, eta, (datetime.now() - started).total_seconds())
    return 0 if eta["errors"] == 0 else 1


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
