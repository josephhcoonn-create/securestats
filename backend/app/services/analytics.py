"""
Analytics service layer.

All public functions accept an ``AsyncSession`` so they compose cleanly
with FastAPI's dependency-injected sessions.  No function manages its own
session — the caller owns the session lifecycle.

Supported stats
───────────────
  batting_avg   SUM(hits) / SUM(at_bats)        formatted  ".302"
  home_runs     SUM(home_runs)                   formatted  "23"
  rbis          SUM(rbis)                        formatted  "45"
  hits          SUM(hits)                        formatted  "67"
  on_base_pct   AVG(on_base_pct)                formatted  ".380"
  slugging_pct  AVG(slugging_pct)               formatted  ".512"
  ops           AVG(obp) + AVG(slg)             formatted  ".892"

Hit probability formula
───────────────────────
  p = 0.5 × recent_avg (last 30 games)
    + 0.3 × career_avg (all-time)
    + 0.2 × league_avg (DB-wide)

  95% CI uses a normal approximation on the recent-sample at-bats.
  Confidence label: low (<15 AB), medium (15–49 AB), high (≥50 AB).
"""

import math
from datetime import date, timedelta

from fastapi import HTTPException, status
from sqlalchemy import Float, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.batting_stats import BattingStats
from app.models.game import Game
from app.models.player import Player
from app.schemas.stats import (
    BattingLeadersResponse,
    ComparisonPlayerStats,
    HitProbabilityResponse,
    LeaderEntry,
    PlayerComparisonResponse,
    StreakEntry,
    StreaksResponse,
    TeamRankingEntry,
    TeamRankingsResponse,
    fmt_avg,
    fmt_int,
    fmt_pct,
)

# ── Constants ─────────────────────────────────────────────────────────────────

VALID_STATS = frozenset(
    {"batting_avg", "home_runs", "rbis", "hits", "on_base_pct", "slugging_pct", "ops"}
)
MIN_AB_LEADERS = 10     # minimum at-bats to qualify for batting leaders
MIN_AB_TEAMS = 50       # minimum team at-bats to appear in team rankings
RECENT_GAMES_WINDOW = 10  # games used for "recent form" in comparison
FALLBACK_LEAGUE_AVG = 0.243  # MLB historical average, used when DB is empty

FINAL_STATUSES = ("Final", "Game Over", "Completed Early")


# ── SQL helpers ───────────────────────────────────────────────────────────────


def _stat_aggregate(stat: str):
    """
    Return the SQLAlchemy aggregate expression for *stat*.

    Uses ``NULLIF(SUM(at_bats), 0)`` for batting_avg so division by zero
    becomes NULL rather than a DB error.
    """
    if stat == "batting_avg":
        return func.sum(BattingStats.hits).cast(Float) / func.nullif(
            func.sum(BattingStats.at_bats), 0
        )
    if stat == "home_runs":
        return func.sum(BattingStats.home_runs)
    if stat == "rbis":
        return func.sum(BattingStats.rbis)
    if stat == "hits":
        return func.sum(BattingStats.hits)
    if stat == "on_base_pct":
        return func.avg(BattingStats.on_base_pct)
    if stat == "slugging_pct":
        return func.avg(BattingStats.slugging_pct)
    if stat == "ops":
        # AVG ignores NULLs in PostgreSQL; returns NULL only when ALL rows are NULL
        return func.avg(BattingStats.on_base_pct) + func.avg(BattingStats.slugging_pct)
    raise ValueError(f"Unknown stat: {stat!r}. Valid: {sorted(VALID_STATS)}")


def _fmt_display(stat: str, value: float | None) -> str:
    """Pre-format a stat value for UI display."""
    if value is None:
        return "---"
    if stat in ("batting_avg", "on_base_pct", "slugging_pct", "ops"):
        return fmt_avg(value)
    return fmt_int(value)


# ── 1. Batting leaders ────────────────────────────────────────────────────────


async def get_batting_leaders(
    session: AsyncSession,
    stat: str,
    limit: int = 10,
    days: int | None = None,
) -> BattingLeadersResponse:
    """
    Return the top *limit* players ranked by *stat* over the last *days*
    calendar days (all-time when *days* is None).
    """
    if stat not in VALID_STATS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid stat '{stat}'. Valid: {sorted(VALID_STATS)}",
        )

    date_filters = [Game.status.in_(FINAL_STATUSES)]
    if days:
        date_filters.append(Game.date >= date.today() - timedelta(days=days))

    q = (
        select(
            Player.id.label("player_id"),
            Player.mlb_id,
            Player.full_name,
            Player.team,
            Player.position,
            func.count(BattingStats.id).label("games_played"),
            func.coalesce(func.sum(BattingStats.at_bats), 0).label("total_ab"),
            _stat_aggregate(stat).label("stat_value"),
        )
        .join(BattingStats, Player.id == BattingStats.player_id)
        .join(Game, BattingStats.game_id == Game.id)
        .where(*date_filters)
        .group_by(
            Player.id,
            Player.mlb_id,
            Player.full_name,
            Player.team,
            Player.position,
        )
        .having(func.sum(BattingStats.at_bats) >= MIN_AB_LEADERS)
        .order_by(text("stat_value DESC NULLS LAST"))
        .limit(limit)
    )

    rows = (await session.execute(q)).all()

    leaders = [
        LeaderEntry(
            rank=i + 1,
            player_id=r.player_id,
            mlb_id=r.mlb_id,
            full_name=r.full_name,
            team=r.team,
            position=r.position,
            games_played=r.games_played,
            at_bats=r.total_ab,
            value=float(r.stat_value) if r.stat_value is not None else None,
            display_value=_fmt_display(stat, float(r.stat_value) if r.stat_value is not None else None),
        )
        for i, r in enumerate(rows)
    ]

    return BattingLeadersResponse(
        stat=stat,
        days=days,
        min_at_bats=MIN_AB_LEADERS,
        leaders=leaders,
    )


# ── 2. Team rankings ──────────────────────────────────────────────────────────


async def get_team_rankings(
    session: AsyncSession,
    stat: str,
) -> TeamRankingsResponse:
    """
    Return all teams ranked by aggregate *stat* across all final games.
    """
    if stat not in VALID_STATS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid stat '{stat}'. Valid: {sorted(VALID_STATS)}",
        )

    q = (
        select(
            Player.team,
            func.count(BattingStats.id).label("games_played"),
            func.coalesce(func.sum(BattingStats.at_bats), 0).label("total_ab"),
            _stat_aggregate(stat).label("stat_value"),
        )
        .join(BattingStats, Player.id == BattingStats.player_id)
        .join(Game, BattingStats.game_id == Game.id)
        .where(Game.status.in_(FINAL_STATUSES))
        .group_by(Player.team)
        .having(func.sum(BattingStats.at_bats) >= MIN_AB_TEAMS)
        .order_by(text("stat_value DESC NULLS LAST"))
    )

    rows = (await session.execute(q)).all()

    rankings = [
        TeamRankingEntry(
            rank=i + 1,
            team=r.team,
            games_played=r.games_played,
            at_bats=r.total_ab,
            value=float(r.stat_value) if r.stat_value is not None else None,
            display_value=_fmt_display(stat, float(r.stat_value) if r.stat_value is not None else None),
        )
        for i, r in enumerate(rows)
    ]

    return TeamRankingsResponse(stat=stat, rankings=rankings)


# ── 3. Hit probability ────────────────────────────────────────────────────────


async def calculate_hit_probability(
    session: AsyncSession,
    player_id: int,
) -> HitProbabilityResponse:
    """
    Estimate the probability of a hit on the player's next at-bat.

    Formula: 0.5 × recent_avg + 0.3 × career_avg + 0.2 × league_avg

    The 95% confidence interval is computed via normal approximation
    on the recent-sample at-bat count.
    """
    player = await session.get(Player, player_id)
    if player is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Player {player_id} not found",
        )

    # ── Recent (last 30 days of final games) ──────────────────────────────────
    cutoff = date.today() - timedelta(days=30)
    recent_row = (
        await session.execute(
            select(
                func.coalesce(func.sum(BattingStats.at_bats), 0).label("ab"),
                func.coalesce(func.sum(BattingStats.hits), 0).label("h"),
                func.count(BattingStats.id).label("games"),
            )
            .join(Game, BattingStats.game_id == Game.id)
            .where(
                BattingStats.player_id == player_id,
                Game.date >= cutoff,
                Game.status.in_(FINAL_STATUSES),
            )
        )
    ).one()

    recent_ab: int = recent_row.ab or 0
    recent_hits: int = recent_row.h or 0
    recent_games: int = recent_row.games or 0
    recent_avg: float | None = (recent_hits / recent_ab) if recent_ab > 0 else None

    # ── Career ────────────────────────────────────────────────────────────────
    career_row = (
        await session.execute(
            select(
                func.coalesce(func.sum(BattingStats.at_bats), 0).label("ab"),
                func.coalesce(func.sum(BattingStats.hits), 0).label("h"),
            ).where(BattingStats.player_id == player_id)
        )
    ).one()

    career_ab: int = career_row.ab or 0
    career_hits: int = career_row.h or 0
    career_avg: float | None = (career_hits / career_ab) if career_ab > 0 else None

    # ── League ────────────────────────────────────────────────────────────────
    league_row = (
        await session.execute(
            select(
                func.coalesce(func.sum(BattingStats.at_bats), 0).label("ab"),
                func.coalesce(func.sum(BattingStats.hits), 0).label("h"),
            ).join(Game, BattingStats.game_id == Game.id).where(
                Game.status.in_(FINAL_STATUSES)
            )
        )
    ).one()

    league_ab: int = league_row.ab or 0
    league_hits: int = league_row.h or 0
    league_avg: float = (
        (league_hits / league_ab) if league_ab > 0 else FALLBACK_LEAGUE_AVG
    )

    # ── Weighted probability ──────────────────────────────────────────────────
    # Fall back to career if no recent data; fall back to league if no career data
    eff_recent = recent_avg if recent_avg is not None else (career_avg or league_avg)
    eff_career = career_avg if career_avg is not None else league_avg

    probability = 0.5 * eff_recent + 0.3 * eff_career + 0.2 * league_avg
    probability = max(0.0, min(1.0, probability))

    # ── 95% CI via normal approximation ──────────────────────────────────────
    n = recent_ab if recent_ab > 0 else 1  # avoid division by zero
    se = math.sqrt(probability * (1.0 - probability) / n)
    ci_lower = max(0.0, probability - 1.96 * se)
    ci_upper = min(1.0, probability + 1.96 * se)

    # ── Confidence label ──────────────────────────────────────────────────────
    if recent_ab < 15:
        confidence = "low"
    elif recent_ab < 50:
        confidence = "medium"
    else:
        confidence = "high"

    return HitProbabilityResponse(
        player_id=player.id,
        mlb_id=player.mlb_id,
        full_name=player.full_name,
        team=player.team,
        recent_avg=round(recent_avg, 3) if recent_avg is not None else None,
        career_avg=round(career_avg, 3) if career_avg is not None else None,
        league_avg=round(league_avg, 3),
        hit_probability=round(probability, 3),
        display_probability=fmt_pct(probability),
        ci_lower=round(ci_lower, 3),
        ci_upper=round(ci_upper, 3),
        display_ci=f"[{fmt_pct(ci_lower)}, {fmt_pct(ci_upper)}]",
        recent_games=recent_games,
        recent_at_bats=recent_ab,
        confidence=confidence,
    )


# ── 4. Hot / cold streaks ─────────────────────────────────────────────────────


async def get_hot_cold_streaks(
    session: AsyncSession,
    streak_type: str = "both",
    min_games: int = 5,
) -> StreaksResponse:
    """
    Find players whose batting average across their last *min_games* final
    games is >= .350 (hot) or <= .150 (cold).

    Uses a window-function subquery so only the N most-recent games per
    player contribute to the average.
    """
    HOT_THRESHOLD = 0.350
    COLD_THRESHOLD = 0.150

    # ── Subquery 1: rank each player's games newest → oldest ─────────────────
    rn_col = func.row_number().over(
        partition_by=BattingStats.player_id,
        order_by=Game.date.desc(),
    ).label("rn")

    ranked = (
        select(
            BattingStats.player_id,
            BattingStats.at_bats,
            BattingStats.hits,
            rn_col,
        )
        .join(Game, BattingStats.game_id == Game.id)
        .where(Game.status.in_(FINAL_STATUSES))
        .subquery()
    )

    # ── Subquery 2: aggregate the last min_games per player ──────────────────
    recent = (
        select(
            ranked.c.player_id,
            func.count(ranked.c.player_id).label("games"),
            func.sum(ranked.c.hits).label("total_hits"),
            func.sum(ranked.c.at_bats).label("total_ab"),
            (
                func.sum(ranked.c.hits).cast(Float)
                / func.nullif(func.sum(ranked.c.at_bats), 0)
            ).label("period_avg"),
        )
        .where(ranked.c.rn <= min_games)
        .group_by(ranked.c.player_id)
        .having(
            func.count(ranked.c.player_id) >= min_games,
            func.sum(ranked.c.at_bats) >= min_games,  # basic qualifier
        )
        .subquery()
    )

    # ── Main query: join with players and apply streak filter ────────────────
    q = (
        select(Player, recent)
        .join(recent, Player.id == recent.c.player_id)
    )

    if streak_type == "hot":
        q = q.where(recent.c.period_avg >= HOT_THRESHOLD)
    elif streak_type == "cold":
        q = q.where(recent.c.period_avg <= COLD_THRESHOLD)
    else:  # "both"
        q = q.where(
            (recent.c.period_avg >= HOT_THRESHOLD)
            | (recent.c.period_avg <= COLD_THRESHOLD)
        )

    q = q.order_by(recent.c.period_avg.desc())
    rows = (await session.execute(q)).all()

    entries: list[StreakEntry] = []
    for row in rows:
        # select(Player, recent_subquery) → row[0] is the ORM instance;
        # subquery columns are accessible by their label names on the Row.
        player: Player = row[0]
        avg_val = float(row.period_avg) if row.period_avg is not None else None
        stype = (
            "hot"
            if avg_val is not None and avg_val >= HOT_THRESHOLD
            else "cold"
        )
        entries.append(
            StreakEntry(
                player_id=player.id,
                mlb_id=player.mlb_id,
                full_name=player.full_name,
                team=player.team,
                position=player.position,
                streak_type=stype,
                games=row.games,
                hits=row.total_hits or 0,
                at_bats=row.total_ab or 0,
                period_avg=round(avg_val, 3) if avg_val is not None else None,
                display_avg=fmt_avg(avg_val),
            )
        )

    return StreaksResponse(
        streak_type=streak_type,
        min_games=min_games,
        hot_threshold=HOT_THRESHOLD,
        cold_threshold=COLD_THRESHOLD,
        streaks=entries,
    )


# ── 5. Player comparison ──────────────────────────────────────────────────────


async def get_player_comparison(
    session: AsyncSession,
    player_ids: list[int],
) -> PlayerComparisonResponse:
    """
    Return side-by-side career and recent-form stats for the given players.

    Also returns a ``leaders`` dict mapping each stat name to the player_id
    that leads among the compared players.
    """
    if not player_ids:
        return PlayerComparisonResponse(players=[], leaders={})

    players = (
        await session.execute(
            select(Player)
            .where(Player.id.in_(player_ids))
            .order_by(Player.full_name)
        )
    ).scalars().all()

    found_ids = {p.id for p in players}
    missing = set(player_ids) - found_ids
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Players not found: {sorted(missing)}",
        )

    comparison_entries: list[ComparisonPlayerStats] = []

    for player in players:
        # ── Career stats ──────────────────────────────────────────────────────
        career = (
            await session.execute(
                select(
                    func.count(BattingStats.id).label("games"),
                    func.coalesce(func.sum(BattingStats.at_bats), 0).label("ab"),
                    func.coalesce(func.sum(BattingStats.hits), 0).label("h"),
                    func.coalesce(func.sum(BattingStats.home_runs), 0).label("hr"),
                    func.coalesce(func.sum(BattingStats.rbis), 0).label("rbi"),
                    func.avg(BattingStats.on_base_pct).label("obp"),
                    func.avg(BattingStats.slugging_pct).label("slg"),
                ).where(BattingStats.player_id == player.id)
            )
        ).one()

        c_ab: int = career.ab or 0
        c_hits: int = career.h or 0
        c_obp: float | None = float(career.obp) if career.obp is not None else None
        c_slg: float | None = float(career.slg) if career.slg is not None else None
        c_avg: float | None = (c_hits / c_ab) if c_ab > 0 else None
        c_ops: float | None = (
            round(c_obp + c_slg, 3)
            if c_obp is not None and c_slg is not None
            else None
        )

        # ── Recent form (last RECENT_GAMES_WINDOW games) ──────────────────────
        rn_col = func.row_number().over(
            partition_by=BattingStats.player_id,
            order_by=Game.date.desc(),
        ).label("rn")

        ranked = (
            select(BattingStats.player_id, BattingStats.at_bats, BattingStats.hits, rn_col)
            .join(Game, BattingStats.game_id == Game.id)
            .where(
                BattingStats.player_id == player.id,
                Game.status.in_(FINAL_STATUSES),
            )
            .subquery()
        )

        recent = (
            await session.execute(
                select(
                    func.count(ranked.c.player_id).label("games"),
                    func.coalesce(func.sum(ranked.c.at_bats), 0).label("ab"),
                    func.coalesce(func.sum(ranked.c.hits), 0).label("h"),
                )
                .where(ranked.c.rn <= RECENT_GAMES_WINDOW)
            )
        ).one()

        r_ab: int = recent.ab or 0
        r_hits: int = recent.h or 0
        r_avg: float | None = (r_hits / r_ab) if r_ab > 0 else None

        comparison_entries.append(
            ComparisonPlayerStats(
                player_id=player.id,
                mlb_id=player.mlb_id,
                full_name=player.full_name,
                team=player.team,
                position=player.position,
                games_played=career.games or 0,
                at_bats=c_ab,
                hits=c_hits,
                home_runs=career.hr or 0,
                rbis=career.rbi or 0,
                batting_avg=round(c_avg, 3) if c_avg is not None else None,
                on_base_pct=round(c_obp, 3) if c_obp is not None else None,
                slugging_pct=round(c_slg, 3) if c_slg is not None else None,
                ops=c_ops,
                recent_games=recent.games or 0,
                recent_avg=round(r_avg, 3) if r_avg is not None else None,
                display_avg=fmt_avg(c_avg),
                display_ops=fmt_avg(c_ops),
                display_recent_avg=fmt_avg(r_avg),
            )
        )

    # ── Leaders dict ──────────────────────────────────────────────────────────
    def _leader(entries: list[ComparisonPlayerStats], key: str) -> int | None:
        valid = [e for e in entries if getattr(e, key) is not None]
        return max(valid, key=lambda e: getattr(e, key)).player_id if valid else None

    leaders: dict[str, int | None] = {
        "batting_avg": _leader(comparison_entries, "batting_avg"),
        "home_runs": _leader(comparison_entries, "home_runs"),
        "rbis": _leader(comparison_entries, "rbis"),
        "hits": _leader(comparison_entries, "hits"),
        "ops": _leader(comparison_entries, "ops"),
        "recent_avg": _leader(comparison_entries, "recent_avg"),
    }

    return PlayerComparisonResponse(players=comparison_entries, leaders=leaders)
