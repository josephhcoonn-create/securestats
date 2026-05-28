"""
Shared test fixtures — JSON snapshots of upstream API responses, plus
small loader helpers so tests can stop inlining 80-line fixtures.

JSON files
----------
  boxscore_823462.json                 — MLB Stats API /game/{id}/boxscore
  schedule_2026_05_20.json             — MLB Stats API /schedule
  odds_api_2_books_3_markets.json      — The Odds API /v4/sports/baseball_mlb/odds
                                          (DraftKings: h2h + spreads + totals,
                                           FanDuel: h2h only — exercises the
                                           "book skipped some markets" branch)
"""
from __future__ import annotations

import json
from pathlib import Path

_FIXTURES_DIR = Path(__file__).resolve().parent


def load_json(name: str) -> object:
    """Load `tests/fixtures/{name}` as parsed JSON."""
    return json.loads((_FIXTURES_DIR / name).read_text(encoding="utf-8"))


def odds_api_sample() -> list[dict]:
    """One MLB game, two bookmakers, three markets — the canonical Odds
    API response shape used across the parser, matcher, and persistence
    tests. Mutate copies, not the cached object."""
    data = load_json("odds_api_2_books_3_markets.json")
    assert isinstance(data, list)
    return data
