from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


class Settings(BaseModel):
    """Runtime configuration loaded from a YAML file (see config.example.yaml)."""

    app_name: str = "RTSP Recorder"
    environment: str = "development"
    database_path: Path = Path("data/rtsp_recorder.sqlite3")
    recording_path: Path = Path("recordings")
    log_path: Path = Path("logs")

    # retention and storage
    retention_days: int = 30
    minimum_free_disk_gb: float = 5.0
    # when free space drops below the minimum, the oldest recordings are deleted until free
    # space is back above minimum + margin (so files are not deleted one at a time)
    free_disk_margin_gb: float = 1.0
    disk_check_interval_seconds: int = 60
    cleanup_interval_seconds: int = 3600
    event_retention_days: int = 30
    max_events: int = 20000

    # ffmpeg and watchdog
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    restart_delay_seconds: float = 5
    max_restart_delay_seconds: float = 300
    segment_duration_seconds: int = 900
    watchdog_interval_seconds: float = 5
    file_stale_seconds: float = 120
    rtsp_timeout_seconds: int = 10

    # web server and authentication
    web_host: str = "0.0.0.0"
    web_port: int = 8000
    admin_username: str = "admin"
    session_hours: int = 12
    # true when the dashboard is served over HTTPS (e.g. behind a reverse proxy)
    cookie_secure: bool = False
    cors_origins: list[str] = Field(default_factory=list)

    logging_level: str = "INFO"

    @field_validator(
        "retention_days",
        "restart_delay_seconds",
        "max_restart_delay_seconds",
        "segment_duration_seconds",
        "watchdog_interval_seconds",
        "file_stale_seconds",
        "cleanup_interval_seconds",
        "disk_check_interval_seconds",
        "rtsp_timeout_seconds",
        "event_retention_days",
        "max_events",
        "session_hours",
    )
    @classmethod
    def validate_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("value must be greater than zero")
        return value

    @field_validator("minimum_free_disk_gb", "free_disk_margin_gb")
    @classmethod
    def validate_non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError("value cannot be negative")
        return value

    def resolved(self) -> Settings:
        """Copy with absolute paths, so stored file names never depend on the working directory."""
        return self.model_copy(
            update={
                "database_path": self.database_path.expanduser().resolve(),
                "recording_path": self.recording_path.expanduser().resolve(),
                "log_path": self.log_path.expanduser().resolve(),
            }
        )


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as config_file:
        data = yaml.safe_load(config_file) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Configuration file {path} must contain a YAML mapping")
    return data


def prepare_directories(settings: Settings) -> None:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    settings.recording_path.mkdir(parents=True, exist_ok=True)
    settings.log_path.mkdir(parents=True, exist_ok=True)


def load_settings(config_path: Path | None = None) -> Settings:
    selected_path = config_path or Path(os.getenv("RTSP_RECORDER_CONFIG", "config.yaml"))
    settings = Settings.model_validate(_read_yaml(selected_path)).resolved()
    prepare_directories(settings)
    return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
