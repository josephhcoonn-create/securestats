"""
PitcherStats — season-level pitching aggregates for one player in one
season. Populated by an ETL extension (TODO) and consumed by the
enhanced hit-probability model in ``analytics.calculate_enhanced_hit_probability``.

When a pitcher has no row in this table the model falls back to the
league baselines defined in :mod:`app.services.analytics`.
"""
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PitcherStats(Base):
    __tablename__ = "pitcher_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("players.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    season: Mapped[int] = mapped_column(Integer, nullable=False)

    # Counting stats
    games: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    innings_pitched: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    hits_allowed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    walks_allowed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    strikeouts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Rate stats — nullable so we can distinguish "no data yet" from "0.00"
    era: Mapped[float | None] = mapped_column(Float, nullable=True)
    whip: Mapped[float | None] = mapped_column(Float, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    player: Mapped["Player"] = relationship("Player", lazy="selectin")  # noqa: F821

    __table_args__ = (
        UniqueConstraint("player_id", "season", name="uq_pitcher_stats_player_season"),
    )
