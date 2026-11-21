from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask

from app.api.dependencies import get_camera_service, get_playback_service, get_recording_service
from app.schemas.api import RecordingRead
from app.services.camera_service import CameraService
from app.services.playback_service import PlaybackBusyError, PlaybackService
from app.services.recording_service import RecordingService

router = APIRouter(prefix="/recordings", tags=["recordings"])


def _existing_file(recording_service: RecordingService, recording_id: int) -> Path:
    recording = recording_service.get_recording(recording_id)
    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")
    path = recording_service.file_path(recording)
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Recording outside storage"
        )
    if not path.is_file():
        recording_service.delete_by_filename(recording.filename)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording file missing")
    return path


@router.get("", response_model=list[RecordingRead])
def list_recordings(
    camera_id: int | None = Query(default=None),
    start: datetime | None = Query(default=None, description="only recordings ending after this"),
    end: datetime | None = Query(default=None, description="only recordings starting before this"),
    limit: int = Query(default=500, ge=1, le=5000),
    camera_service: CameraService = Depends(get_camera_service),
    recording_service: RecordingService = Depends(get_recording_service),
) -> list[RecordingRead]:
    if camera_id is not None and camera_service.get_camera(camera_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    recordings = recording_service.list_recordings(
        camera_id=camera_id, limit=limit, start=start, end=end
    )
    return [RecordingRead.model_validate(recording.__dict__) for recording in recordings]


@router.get("/{recording_id}/download")
def download_recording(
    recording_id: int,
    recording_service: RecordingService = Depends(get_recording_service),
) -> FileResponse:
    path = _existing_file(recording_service, recording_id)
    return FileResponse(path, media_type="video/x-matroska", filename=path.name)


@router.get("/{recording_id}/stream")
def stream_recording(
    recording_id: int,
    recording_service: RecordingService = Depends(get_recording_service),
) -> FileResponse:
    """The original MKV, inline (supports range requests)."""
    path = _existing_file(recording_service, recording_id)
    return FileResponse(path, media_type="video/x-matroska", content_disposition_type="inline")


@router.get("/{recording_id}/play")
def play_recording(
    recording_id: int,
    recording_service: RecordingService = Depends(get_recording_service),
    playback_service: PlaybackService = Depends(get_playback_service),
) -> StreamingResponse:
    """The recording remuxed to MP4 for browser playback (video not transcoded)."""
    path = _existing_file(recording_service, recording_id)
    try:
        body = playback_service.stream_mp4(path)
    except PlaybackBusyError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="ffmpeg not available"
        ) from exc
    # the background task also runs when the client disconnects early
    return StreamingResponse(body, media_type="video/mp4", background=BackgroundTask(body.close))


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
