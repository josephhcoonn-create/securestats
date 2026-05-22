from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.etl import router as etl_router
from app.api.games import router as games_router
from app.api.players import router as players_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth_router)
api_router.include_router(etl_router)
api_router.include_router(players_router)
api_router.include_router(games_router)
