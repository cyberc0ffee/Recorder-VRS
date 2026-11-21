from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.services.auth_service import AuthService, User
from app.services.camera_service import CameraService
from app.services.cleanup_service import CleanupService
from app.services.event_service import EventService
from app.services.playback_service import PlaybackService
from app.services.recording_service import RecordingService
from app.services.system_service import SystemService
from app.workers.manager import WorkerManager

SESSION_COOKIE = "rtsp_recorder_session"
# custom header required on state-changing requests: a cross-site form or image cannot
# send it, and a cross-site script would need a CORS preflight that is not allowed
CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "rtsp-recorder"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


def get_camera_service(request: Request) -> CameraService:
    return request.app.state.camera_service


def get_event_service(request: Request) -> EventService:
    return request.app.state.event_service


def get_recording_service(request: Request) -> RecordingService:
    return request.app.state.recording_service


def get_cleanup_service(request: Request) -> CleanupService:
    return request.app.state.cleanup_service


def get_worker_manager(request: Request) -> WorkerManager:
    return request.app.state.worker_manager


def get_system_service(request: Request) -> SystemService:
    return request.app.state.system_service


def get_playback_service(request: Request) -> PlaybackService:
    return request.app.state.playback_service


def check_csrf(request: Request) -> None:
    if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing request header")


def require_user(request: Request) -> User:
    check_csrf(request)
    user = get_auth_service(request).user_for_token(request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    request.state.user = user
    return user
