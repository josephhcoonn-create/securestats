from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class BattingStats(Base):
    __tablename__ = "batting_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("players.id", ondelete="CASCADE"), nullable=False
    )
    game_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("games.id", ondelete="CASCADE"), nullable=False
    )
    at_bats: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    home_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rbis: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    batting_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    on_base_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    slugging_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    player: Mapped["Player"] = relationship("Player", lazy="selectin")  # noqa: F821
    game: Mapped["Game"] = relationship("Game", lazy="selectin")  # noqa: F821

    __table_args__ = (
        Index("ix_batting_stats_player_id", "player_id"),
        Index("ix_batting_stats_game_id", "game_id"),
    )
