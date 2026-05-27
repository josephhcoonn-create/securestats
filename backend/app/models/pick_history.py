"""
PickHistory — every daily pick we surface, snapshotted at prediction
time so we can grade the model's accuracy after the game finishes.

Each row represents one player-game pair where the enhanced hit-prob
model passed the daily-picks threshold. ``actual_result`` starts as
``'pending'`` and is updated to ``'hit'`` or ``'no_hit'`` by the daily
ETL once the game reaches Final status.

``factors_snapshot`` stores the full factor breakdown that was used
at prediction time so we can audit *why* a pick was made later (e.g.
"low pitcher ERA dominated this projection") even if the upstream
data has since drifted.
"""
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PickHistory(Base):
    __tablename__ = "pick_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("players.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    game_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("games.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    predicted_probability: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)

    # 'pending' | 'hit' | 'no_hit'. Plain string for portability; the
    # service layer enforces the value set via the ActualResult literal.
    actual_result: Mapped[str] = mapped_column(
        String(10), nullable=False, default="pending"
    )

    factors_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    player: Mapped["Player"] = relationship("Player", lazy="selectin")  # noqa: F821
    game: Mapped["Game"] = relationship("Game", lazy="selectin")  # noqa: F821

    __table_args__ = (
        # One snapshot per (player, game) — duplicate /picks/today calls
        # on the same day must be no-ops.
        UniqueConstraint(
            "player_id", "game_id", name="uq_pick_history_player_game"
        ),
    )
