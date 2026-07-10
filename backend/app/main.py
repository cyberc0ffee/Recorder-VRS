from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import get_settings
from app.core.database import Database
from app.core.logging import configure_logging
from app.services.camera_service import CameraService
from app.services.cleanup_service import CleanupService
from app.services.event_service import EventService
from app.services.recording_service import RecordingService
from app.services.storage_service import StorageService
from app.services.system_service import SystemService
from app.workers.manager import WorkerManager


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings)

    database = Database(settings.database_path)
    database.init_schema()

    camera_service = CameraService(database)
    event_service = EventService(database)
    recording_service = RecordingService(database)
    storage_service = StorageService(settings)
    worker_manager = WorkerManager(
        settings=settings,
        camera_service=camera_service,
        storage_service=storage_service,
        event_service=event_service,
        recording_service=recording_service,
    )
    cleanup_service = CleanupService(
        settings=settings,
        storage_service=storage_service,
        recording_service=recording_service,
        event_service=event_service,
    )
    system_service = SystemService(storage_service, worker_manager)

    app.state.settings = settings
    app.state.database = database
    app.state.camera_service = camera_service
    app.state.event_service = event_service
    app.state.recording_service = recording_service
    app.state.storage_service = storage_service
    app.state.worker_manager = worker_manager
    app.state.cleanup_service = cleanup_service
    app.state.system_service = system_service

    cleanup_service.start_background()
    worker_manager.autostart()
    event_service.record("INFO", "RTSP Recorder started")

    try:
        yield
    finally:
        event_service.record("INFO", "RTSP Recorder stopping")
        cleanup_service.stop_background()
        worker_manager.shutdown()
        database.close()


app = FastAPI(
    title="RTSP Recorder",
    description="Lightweight RTSP Network Video Recorder",
    version="0.1.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def serve_frontend(path: str) -> FileResponse:
        requested_file = frontend_dist / path
        if requested_file.exists() and requested_file.is_file():
            return FileResponse(requested_file)
        return FileResponse(frontend_dist / "index.html")

