from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

from app.api.dependencies import get_camera_service, get_recording_service
from app.schemas.api import RecordingRead
from app.services.camera_service import CameraService
from app.services.recording_service import RecordingService


router = APIRouter(prefix="/recordings", tags=["recordings"])


@router.get("", response_model=list[RecordingRead])
def list_recordings(
    camera_id: int | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=1000),
    camera_service: CameraService = Depends(get_camera_service),
    recording_service: RecordingService = Depends(get_recording_service),
) -> list[RecordingRead]:
    if camera_id is not None and camera_service.get_camera(camera_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    return [
        RecordingRead.model_validate(recording.__dict__)
        for recording in recording_service.list_recordings(camera_id=camera_id, limit=limit)
    ]


@router.get("/{recording_id}/download")
def download_recording(
    recording_id: int,
    recording_service: RecordingService = Depends(get_recording_service),
) -> FileResponse:
    recording = recording_service.get_recording(recording_id)
    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")
    file_path = Path(recording.filename)
    if not file_path.exists():
        recording_service.delete_by_filename(recording.filename)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording file missing")
    return FileResponse(
        file_path,
        media_type="video/x-matroska",
        filename=file_path.name,
    )


@router.get("/{recording_id}/stream")
def stream_recording(
    recording_id: int,
    recording_service: RecordingService = Depends(get_recording_service),
) -> FileResponse:
    return download_recording(recording_id, recording_service)


@router.delete("/{recording_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recording(
    recording_id: int,
    recording_service: RecordingService = Depends(get_recording_service),
) -> None:
    try:
        recording = recording_service.delete_recording(recording_id)
    except OSError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")
