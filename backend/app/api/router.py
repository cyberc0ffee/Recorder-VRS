from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import cameras, cleanup, events, recordings, system


api_router = APIRouter(prefix="/api")
api_router.include_router(cameras.router)
api_router.include_router(system.router)
api_router.include_router(events.router)
api_router.include_router(cleanup.router)
api_router.include_router(recordings.router)
