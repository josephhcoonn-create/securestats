from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mlb_game_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    home_team: Mapped[str] = mapped_column(String(100), nullable=False)
    away_team: Mapped[str] = mapped_column(String(100), nullable=False)
    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="scheduled")

    # Probable starters — populated by ETL via MLB API
    # ?hydrate=probablePitcher. Nullable because (a) probable pitchers
    # aren't announced for every game, and (b) they're irrelevant for
    # already-final games. FK to players so we get the handedness +
    # season stats for free in the enhanced hit-prob model.
    home_probable_pitcher_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("players.id", ondelete="SET NULL"),
        nullable=True,
    )
    away_probable_pitcher_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("players.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_games_mlb_game_id", "mlb_game_id"),)
