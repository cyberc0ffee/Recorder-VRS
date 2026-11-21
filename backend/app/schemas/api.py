from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


def _check_rtsp_url(value: str) -> str:
    if not value.startswith(("rtsp://", "rtsps://")):
        raise ValueError("RTSP URL must start with rtsp:// or rtsps://")
    if any(ch.isspace() for ch in value):
        raise ValueError("RTSP URL must not contain spaces")
    return value


class CameraCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    rtsp_url: str = Field(min_length=7, max_length=2048)
    enabled: bool = True
    autostart: bool = True

    @field_validator("rtsp_url")
    @classmethod
    def validate_rtsp_url(cls, value: str) -> str:
        return _check_rtsp_url(value)


class CameraUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    # a masked password (user:***@host) keeps the stored one
    rtsp_url: str | None = Field(default=None, min_length=7, max_length=2048)
    enabled: bool | None = None
    autostart: bool | None = None

    @field_validator("rtsp_url")
    @classmethod
    def validate_rtsp_url(cls, value: str | None) -> str | None:
        return None if value is None else _check_rtsp_url(value)


class WorkerStatus(BaseModel):
    camera_id: int
    camera_name: str
    state: str
    online: bool
    recording: bool
    pid: int | None
    started_at: str | None
    stopped_at: str | None
    restart_count: int
    last_error: str | None
    last_exit_code: int | None
    current_file: str | None
    bytes_written: int
    last_file_growth_at: str | None
    next_retry_at: str | None
    last_ffmpeg_message: str | None


class CameraRead(BaseModel):
    id: int
    name: str
    # always masked: passwords never leave the server
    rtsp_url: str
    enabled: bool
    autostart: bool
    created_at: str
    status: WorkerStatus


class EventRead(BaseModel):
    id: int
    timestamp: str
    level: str
    message: str
    camera_id: int | None


class RecordingRead(BaseModel):
    id: int
    camera_id: int
    filename: str
    duration: float | None
    size: int
    start_time: str | None
    end_time: str | None


class CleanupRead(BaseModel):
    deleted_files: int
    deleted_bytes: int
    deleted_for_space: int
    pruned_database_rows: int
    pruned_events: int
    errors: list[str]


class SystemRead(BaseModel):
    process_id: int
    cpu_percent: float | None
    ram: dict[str, Any] | None
    disk: dict[str, Any]
    cameras_online: int
    cameras_offline: int
    recording_cameras: int
    workers: dict[int, dict[str, Any]]


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=1024)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


class UserRead(BaseModel):
    username: str
    role: str
