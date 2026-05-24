"""
PitcherStats — pitching aggregates for one player.

Two row flavors live in the same table, distinguished by
``is_season_aggregate``:

  * Per-game lines    → is_season_aggregate=False, game_id set, season set
  * Season aggregates → is_season_aggregate=True,  game_id NULL, season set

The two partial unique indexes below enforce that each shape stays
de-duplicated without colliding with the other.

Pitcher handedness lives on :attr:`Player.throws` (the MLB API's
``pitchHand.code``), so this table doesn't carry a separate ``pitch_hand``
column — joining via ``player_id`` is enough.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    func,
    text,
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
    # NULL for season-aggregate rows; set for per-game rows.
    game_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("games.id", ondelete="CASCADE"),
        nullable=True,
    )
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    is_season_aggregate: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    # Counting stats
    games: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    innings_pitched: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    hits_allowed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    earned_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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
        # Partial unique indexes — Postgres allows distinct uniqueness rules
        # for each row flavor without two separate tables.
        Index(
            "uq_pitcher_stats_season",
            "player_id", "season",
            unique=True,
            postgresql_where=text("is_season_aggregate"),
        ),
        Index(
            "uq_pitcher_stats_game",
            "player_id", "game_id",
            unique=True,
            postgresql_where=text("NOT is_season_aggregate"),
        ),
    )
