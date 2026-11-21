from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import (
    get_camera_service,
    get_event_service,
    get_recording_service,
    get_worker_manager,
)
from app.core.security import mask_rtsp_url
from app.models.domain import Camera
from app.schemas.api import CameraCreate, CameraRead, CameraUpdate, RecordingRead, WorkerStatus
from app.services.camera_service import CameraService
from app.services.event_service import EventService
from app.services.recording_service import RecordingService
from app.workers.manager import WorkerManager

router = APIRouter(prefix="/cameras", tags=["cameras"])


def _camera_response(camera: Camera, worker_manager: WorkerManager) -> CameraRead:
    return CameraRead(
        id=camera.id,
        name=camera.name,
        rtsp_url=mask_rtsp_url(camera.rtsp_url),
        enabled=camera.enabled,
        autostart=camera.autostart,
        created_at=camera.created_at,
        status=WorkerStatus.model_validate(worker_manager.status_for_camera(camera)),
    )


def _get_or_404(camera_service: CameraService, camera_id: int) -> Camera:
    camera = camera_service.get_camera(camera_id)
    if camera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    return camera


@router.get("", response_model=list[CameraRead])
def list_cameras(
    camera_service: CameraService = Depends(get_camera_service),
    worker_manager: WorkerManager = Depends(get_worker_manager),
) -> list[CameraRead]:
    return [_camera_response(camera, worker_manager) for camera in camera_service.list_cameras()]


@router.post("", response_model=CameraRead, status_code=status.HTTP_201_CREATED)
def create_camera(
    payload: CameraCreate,
    camera_service: CameraService = Depends(get_camera_service),
    worker_manager: WorkerManager = Depends(get_worker_manager),
    event_service: EventService = Depends(get_event_service),
) -> CameraRead:
    try:
        camera = camera_service.create_camera(
            name=payload.name,
            rtsp_url=payload.rtsp_url,
            enabled=payload.enabled,
            autostart=payload.autostart,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    event_service.record("INFO", f"Camera created: {camera.name}", camera.id)
    if camera.enabled and camera.autostart:
        try:
            worker_manager.start_camera(camera.id)
        except RuntimeError as exc:
            event_service.record(
                "WARNING", f"Autostart skipped for {camera.name}: {exc}", camera.id
            )

    return _camera_response(camera, worker_manager)


@router.get("/{camera_id}", response_model=CameraRead)
def get_camera(
    camera_id: int,
    camera_service: CameraService = Depends(get_camera_service),
    worker_manager: WorkerManager = Depends(get_worker_manager),
) -> CameraRead:
    return _camera_response(_get_or_404(camera_service, camera_id), worker_manager)


@router.put("/{camera_id}", response_model=CameraRead)
def update_camera(
    camera_id: int,
    payload: CameraUpdate,
    camera_service: CameraService = Depends(get_camera_service),
    worker_manager: WorkerManager = Depends(get_worker_manager),
    event_service: EventService = Depends(get_event_service),
) -> CameraRead:
    try:
        camera = camera_service.update_camera(
            camera_id=camera_id,
            name=payload.name,
            rtsp_url=payload.rtsp_url,
            enabled=payload.enabled,
            autostart=payload.autostart,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if camera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")

    try:
        worker_manager.refresh_camera(camera)
    except RuntimeError as exc:
        event_service.record("WARNING", f"Restart skipped for {camera.name}: {exc}", camera.id)
    event_service.record("INFO", f"Camera updated: {camera.name}", camera.id)
    return _camera_response(camera, worker_manager)


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_camera(
    camera_id: int,
    delete_recordings: bool = Query(default=False),
    camera_service: CameraService = Depends(get_camera_service),
    recording_service: RecordingService = Depends(get_recording_service),
    worker_manager: WorkerManager = Depends(get_worker_manager),
    event_service: EventService = Depends(get_event_service),
) -> None:
    camera = _get_or_404(camera_service, camera_id)
    worker_manager.remove_camera(camera_id)
    if delete_recordings:
        removed, failed = recording_service.delete_camera_recordings(camera_id)
        if failed:
            # the camera is kept, so the remaining recordings stay visible and can be retried
            event_service.record(
                "ERROR",
                f"Cannot delete {failed} recordings of {camera.name}; camera not deleted",
                camera.id,
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"{failed} recording files could not be deleted; camera kept",
            )
        suffix = f" and {removed} recordings"
    else:
        suffix = " (recording files kept on disk)"
    camera_service.delete_camera(camera_id)
    event_service.record("INFO", f"Camera deleted: {camera.name}{suffix}")


@router.post("/{camera_id}/start", response_model=WorkerStatus)
def start_camera(
    camera_id: int,
    worker_manager: WorkerManager = Depends(get_worker_manager),
) -> WorkerStatus:
    try:
        status_payload = worker_manager.start_camera(camera_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found"
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return WorkerStatus.model_validate(status_payload)


@router.post("/{camera_id}/stop", response_model=WorkerStatus)
def stop_camera(
    camera_id: int,
    worker_manager: WorkerManager = Depends(get_worker_manager),
) -> WorkerStatus:
    try:
        status_payload = worker_manager.stop_camera(camera_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found"
        ) from exc
    return WorkerStatus.model_validate(status_payload)


@router.get("/{camera_id}/recordings", response_model=list[RecordingRead])
def list_recordings(
    camera_id: int,
    camera_service: CameraService = Depends(get_camera_service),
    recording_service: RecordingService = Depends(get_recording_service),
) -> list[RecordingRead]:
    _get_or_404(camera_service, camera_id)
    return [
        RecordingRead.model_validate(recording.__dict__)
        for recording in recording_service.list_by_camera(camera_id)
    ]
