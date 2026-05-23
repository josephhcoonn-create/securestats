"""
DESTRUCTIVE: drop every table in the configured database and re-run all
Alembic migrations from scratch. Development convenience only.

Safety rails
------------
- Refuses to run when ENVIRONMENT=production.
- Requires the user to type `RESET` at an interactive confirmation prompt
  (skippable with --yes for CI / scripted use).
- Operates on whatever DATABASE_URL points at — verify it before saying yes.

Usage
-----
    docker compose exec backend python -m scripts.reset_db
    docker compose exec backend python -m scripts.reset_db --yes
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import selectors
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from urllib.parse import urlparse  # noqa: E402

from sqlalchemy import text  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import engine as async_engine  # noqa: E402


def _connection_user() -> str | None:
    """Pull the DB role out of DATABASE_URL so we can re-grant the schema."""
    try:
        return urlparse(settings.database_url.replace("+psycopg", "")).username
    except Exception:  # noqa: BLE001
        return None

logger = logging.getLogger("reset_db")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Drop all tables and re-run migrations (dev only).",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation prompt (for CI / scripted use).",
    )
    return p.parse_args()


async def _drop_public_schema() -> None:
    """Nuke and recreate the `public` schema — fastest way to wipe both
    application tables AND the alembic_version bookkeeping in one shot."""
    async with async_engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        # Restore default grants so the configured user can still create.
        await conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
        # Best-effort grant to the connection user (no-op if they already own it).
        user = _connection_user()
        if user:
            try:
                await conn.execute(text(f'GRANT ALL ON SCHEMA public TO "{user}"'))
            except Exception:  # noqa: BLE001
                pass
    logger.info("public schema dropped and recreated")


def _run_alembic_upgrade() -> None:
    """Shell out to `alembic upgrade head` so we use the project's exact config."""
    backend_root = Path(__file__).resolve().parent.parent
    logger.info("running alembic upgrade head…")
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=backend_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit(f"alembic failed with exit code {result.returncode}")
    print(result.stdout.strip())


def _redact_url(url: str) -> str:
    """Hide the password in DATABASE_URL when echoing it back to the user."""
    if "://" not in url or "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    creds, hostpart = rest.split("@", 1)
    if ":" in creds:
        user, _pw = creds.split(":", 1)
        creds = f"{user}:***"
    return f"{scheme}://{creds}@{hostpart}"


def _confirm_or_exit(skip_prompt: bool) -> None:
    if settings.environment.lower() == "production":
        sys.exit("refusing to reset: ENVIRONMENT=production")

    print()
    print("⚠️  About to DROP every table in:")
    print(f"     {_redact_url(settings.database_url)}")
    print(f"     environment = {settings.environment}")
    print()

    if skip_prompt:
        print("--yes given; proceeding without prompt.")
        return

    answer = input('Type "RESET" (exactly) to confirm, anything else to abort: ').strip()
    if answer != "RESET":
        sys.exit("Aborted — nothing was changed.")


async def main() -> int:
    args = _parse_args()
    _confirm_or_exit(skip_prompt=args.yes)

    await _drop_public_schema()
    await async_engine.dispose()  # alembic will open its own sync engine
    _run_alembic_upgrade()

    print("\n✅ Database reset complete. Run `python -m scripts.seed` to repopulate.")
    return 0


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
