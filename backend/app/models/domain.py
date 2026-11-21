from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Camera:
    id: int
    name: str
    rtsp_url: str
    enabled: bool
    autostart: bool
    created_at: str


@dataclass(frozen=True)
class Event:
    id: int
    timestamp: str
    level: str
    message: str
    camera_id: int | None


@dataclass(frozen=True)
class Recording:
    id: int
    camera_id: int
    filename: str
    duration: float | None
    size: int
    start_time: str | None
    end_time: str | None
