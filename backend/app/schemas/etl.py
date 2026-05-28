from pydantic import BaseModel, Field


class ETLTriggerResponse(BaseModel):
    status: str
    run_date: str
    games_processed: int
    players_upserted: int
    stats_inserted: int
    stats_updated: int
    errors: list[str]
    duration_seconds: float
    success: bool


class OddsTriggerResponse(BaseModel):
    """Result envelope for POST /etl/trigger-odds."""

    target_date: str
    rows_inserted: int = Field(
        ...,
        description="GameOdds rows created. Repeated runs within the same minute return 0 because of the (game, book, fetched_at) unique constraint.",
    )
    quota_remaining: int | None = Field(
        None,
        description="x-requests-remaining from The Odds API after this call.",
    )
    quota_used: int | None = Field(
        None,
        description="x-requests-used from The Odds API after this call.",
    )
    duration_seconds: float
    success: bool
