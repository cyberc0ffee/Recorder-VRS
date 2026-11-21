from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import require_user
from app.api.routes import auth, cameras, cleanup, events, recordings, system

api_router = APIRouter(prefix="/api")
# login/logout/me handle authentication themselves
api_router.include_router(auth.router)

protected = APIRouter(dependencies=[Depends(require_user)])
protected.include_router(cameras.router)
protected.include_router(system.router)
protected.include_router(events.router)
protected.include_router(cleanup.router)
protected.include_router(recordings.router)
api_router.include_router(protected)
