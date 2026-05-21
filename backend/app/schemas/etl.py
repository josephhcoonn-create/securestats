from pydantic import BaseModel


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
