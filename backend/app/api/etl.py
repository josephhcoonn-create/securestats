from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.auth.rbac import TokenPayload, require_role
from app.models.user import UserRole
from app.schemas.etl import ETLTriggerResponse
from app.services.etl import run_daily_etl, run_live_update

router = APIRouter(prefix="/etl", tags=["etl"])

_admin = Depends(require_role(UserRole.admin))


@router.post(
    "/trigger",
    response_model=ETLTriggerResponse,
    summary="Manually trigger the ETL pipeline (admin only)",
)
async def trigger_etl(
    live_only: Annotated[
        bool,
        Query(description="True → live-update only (in-progress games); False → full daily ETL"),
    ] = False,
    _: TokenPayload = _admin,
) -> ETLTriggerResponse:
    """
    Admin-only endpoint that synchronously runs the ETL pipeline and returns
    the full result so you can see exactly what was loaded.

    - **live_only=false** (default) — runs the full `run_daily_etl()` pipeline.
    - **live_only=true** — runs `run_live_update()` (faster, in-progress games only).
    """
    result = await run_live_update() if live_only else await run_daily_etl()

    return ETLTriggerResponse(
        status="success" if result.success else "partial_failure",
        run_date=str(result.run_date),
        games_processed=result.games_processed,
        players_upserted=result.players_upserted,
        stats_inserted=result.stats_inserted,
        stats_updated=result.stats_updated,
        errors=result.errors,
        duration_seconds=round(result.duration_seconds, 2),
        success=result.success,
    )
