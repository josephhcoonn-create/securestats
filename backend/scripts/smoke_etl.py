"""
Smoke-test run_etl_for_date() against the live MLB API and local Postgres.
Run from backend/ with:
    $env:PYTHONPATH="."; python scripts/smoke_etl.py
"""
import asyncio
import logging
import selectors
import sys
from datetime import date, timedelta

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)


async def main() -> None:
    from app.services.etl import run_etl_for_date

    # Use yesterday so we're guaranteed Final games
    yesterday = date.today() - timedelta(days=1)
    print(f"Running ETL for {yesterday} (yesterday) ...")
    result = await run_etl_for_date(yesterday)

    print("\n-- ETL Result --")
    print(result.summary())
    print(f"  success={result.success}")
    if result.errors:
        print("Errors:")
        for err in result.errors:
            print(f"  * {err}")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.run(
            main(),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
    else:
        asyncio.run(main())
