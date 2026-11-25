from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.dependencies import CSRF_HEADER
from app.api.router import api_router
from app.core.config import Settings, get_settings, prepare_directories
from app.core.database import Database
from app.core.logging import configure_logging
from app.services.auth_service import AuthService
from app.services.camera_service import CameraService
from app.services.cleanup_service import CleanupService
from app.services.event_service import EventService
from app.services.playback_service import PlaybackService
from app.services.reconcile_service import ReconcileService
from app.services.recording_service import RecordingService
from app.services.storage_service import StorageService
from app.services.system_service import SystemService
from app.workers.manager import WorkerManager

VERSION = "0.2.0"
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)
# Swagger UI loads its assets from a CDN: no CSP on the documentation pages
DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


def build_lifespan(settings: Settings) -> Callable[[FastAPI], AsyncIterator[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        prepare_directories(settings)
        configure_logging(settings)

        database = Database(settings.database_path)
        database.init_schema()

        auth_service = AuthService(database, settings)
        camera_service = CameraService(database)
        event_service = EventService(database)
        recording_service = RecordingService(database, settings.recording_path)
        storage_service = StorageService(settings)

        # the cleanup and the manager need each other: the manager asks the cleanup to free
        # space before refusing a start, the cleanup never deletes files being written
        managers: list[WorkerManager] = []
        cleanup_service = CleanupService(
            settings=settings,
            storage_service=storage_service,
            recording_service=recording_service,
            event_service=event_service,
            active_files=lambda: managers[0].active_files() if managers else set(),
            purge_sessions=auth_service.purge_expired_sessions,
        )
        worker_manager = WorkerManager(
            settings=settings,
            camera_service=camera_service,
            storage_service=storage_service,
            event_service=event_service,
            recording_service=recording_service,
            free_space=cleanup_service.ensure_free_space,
        )
        managers.append(worker_manager)
        reconcile_service = ReconcileService(
            settings=settings,
            camera_service=camera_service,
            storage_service=storage_service,
            recording_service=recording_service,
            active_files=worker_manager.active_files,
        )

        app.state.settings = settings
        app.state.database = database
        app.state.auth_service = auth_service
        app.state.camera_service = camera_service
        app.state.event_service = event_service
        app.state.recording_service = recording_service
        app.state.storage_service = storage_service
        app.state.worker_manager = worker_manager
        app.state.cleanup_service = cleanup_service
        app.state.playback_service = PlaybackService(settings)
        app.state.system_service = SystemService(storage_service, worker_manager)

        auth_service.ensure_admin()
        # recording first: nothing below may delay or prevent it
        worker_manager.autostart()
        worker_manager.start_supervisor()
        try:
            reconcile_service.run()
        except Exception:  # noqa: BLE001 - the index is rebuilt at the next start
            logging.getLogger("rtsp_recorder").exception("Startup reconcile failed")
        cleanup_service.start_background()
        reconcile_service.start_background_probe()
        event_service.record("INFO", f"RTSP Recorder {VERSION} started")

        try:
            yield
        finally:
            event_service.record("INFO", "RTSP Recorder stopping")
            reconcile_service.stop()
            cleanup_service.stop_background()
            worker_manager.shutdown()
            database.close()

    return lifespan


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    dist = dist.resolve()
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def serve_frontend(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        requested = (dist / path).resolve()
        # resolve() collapses "..": anything outside dist falls back to the app shell
        if path and requested.is_relative_to(dist) and requested.is_file():
            return FileResponse(requested)
        return FileResponse(dist / "index.html")


def create_app(
    settings: Settings | None = None, frontend_dist: Path | None = FRONTEND_DIST
) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="RTSP Recorder",
        description="Lightweight RTSP Network Video Recorder",
        version=VERSION,
        lifespan=build_lifespan(settings),
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=["Content-Type", CSRF_HEADER],
        )

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if not request.url.path.startswith(DOCS_PATHS):
            response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    app.include_router(api_router)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/recording", tags=["health"])
    def recording_health(response: Response) -> dict[str, int | str]:
        """For external monitors (Uptime Kuma, Zabbix...): 503 while a camera that should be
        recording is not. Public, like /health: it only returns two counters."""
        counts = app.state.worker_manager.recording_health()
        ok = counts["recording"] >= counts["expected"]
        if not ok:
            response.status_code = 503
        return {"status": "ok" if ok else "degraded", **counts}

    if frontend_dist is not None and (frontend_dist / "index.html").is_file():
        _mount_frontend(app, frontend_dist)
    return app


def __getattr__(name: str) -> FastAPI:
    """`uvicorn app.main:app` keeps working; importing this module has no side effects."""
    if name == "app":
        application = create_app()
        globals()["app"] = application
        return application
    raise AttributeError(name)
