"""
GameOdds — a single snapshot of pre-game lines from one sportsbook for
one of our Games.

The unique constraint on (game_id, sportsbook, fetched_at) lets us pull
the same game multiple times per day for line-movement tracking without
risking duplicate rows. Spreads / totals are nullable because not every
book publishes every market simultaneously.
"""
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class GameOdds(Base):
    __tablename__ = "game_odds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("games.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Book identifier from The Odds API (e.g. "draftkings", "fanduel",
    # "betmgm"). Bounded so the index stays compact.
    sportsbook: Mapped[str] = mapped_column(String(40), nullable=False)

    # Moneyline (American odds): negative = favorite, positive = underdog.
    # Always populated in practice — h2h is the most common market.
    home_moneyline: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_moneyline: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Runline / spread — half-runs in MLB (-1.5 / +1.5 is standard).
    spread_home: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread_away: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Total runs (over/under). One scalar — over and under share it.
    over_under: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Snapshot timestamp from the upstream pull, not row creation.
    # Same game pulled 4x in a day will have 4 rows with the same
    # game_id + sportsbook but different fetched_at values.
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ── Relationship back to Game ─────────────────────────────────────────────
    game: Mapped["Game"] = relationship("Game", lazy="selectin")  # noqa: F821

    __table_args__ = (
        UniqueConstraint(
            "game_id",
            "sportsbook",
            "fetched_at",
            name="uq_game_odds_game_book_fetched",
        ),
        Index("ix_game_odds_game_sportsbook", "game_id", "sportsbook"),
    )
