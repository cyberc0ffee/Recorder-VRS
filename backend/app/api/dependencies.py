from __future__ import annotations

from fastapi import Request

from app.services.camera_service import CameraService
from app.services.cleanup_service import CleanupService
from app.services.event_service import EventService
from app.services.recording_service import RecordingService
from app.services.system_service import SystemService
from app.workers.manager import WorkerManager


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

