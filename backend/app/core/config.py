from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - fallback exists for minimal local runtimes
    yaml = None
from pydantic import BaseModel, Field, field_validator


class Settings(BaseModel):
    """Runtime configuration loaded from YAML plus environment defaults."""

    app_name: str = "RTSP Recorder"
    environment: str = "development"
    database_path: Path = Path("data/rtsp_recorder.sqlite3")
    recording_path: Path = Path("recordings")
    log_path: Path = Path("logs")
    retention_days: int = 30
    minimum_free_disk_gb: float = 5.0
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    restart_delay_seconds: int = 5
    segment_duration_seconds: int = 900
    watchdog_interval_seconds: int = 5
    file_stale_seconds: int = 120
    cleanup_interval_seconds: int = 3600
    web_host: str = "0.0.0.0"
    web_port: int = 8000
    logging_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    @field_validator("retention_days", "restart_delay_seconds", "segment_duration_seconds")
    @classmethod
    def validate_positive_int(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("value must be greater than zero")
        return value

    @field_validator("watchdog_interval_seconds", "file_stale_seconds", "cleanup_interval_seconds")
    @classmethod
    def validate_nonzero_interval(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("interval must be greater than zero")
        return value

    @field_validator("minimum_free_disk_gb")
    @classmethod
    def validate_minimum_free_disk(cls, value: float) -> float:
        if value < 0:
            raise ValueError("minimum free disk cannot be negative")
        return value


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as config_file:
        if yaml is not None:
            data = yaml.safe_load(config_file) or {}
        else:
            data = _read_simple_yaml(config_file.read())
    if not isinstance(data, dict):
        raise ValueError(f"Configuration file {path} must contain a YAML mapping")
    return data


def _read_simple_yaml(raw_yaml: str) -> dict[str, Any]:
    """Parse the simple top-level YAML shape used by config.example.yaml."""

    parsed: dict[str, Any] = {}
    current_list_key: str | None = None
    for raw_line in raw_yaml.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if current_list_key and line.startswith("  - "):
            parsed[current_list_key].append(_parse_scalar(line[4:].strip()))
            continue
        current_list_key = None
        if line.startswith(" ") or ":" not in line:
            raise ValueError("Fallback YAML parser only supports top-level keys and lists")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value:
            parsed[key] = _parse_scalar(value)
        else:
            parsed[key] = []
            current_list_key = key
    return parsed


def _parse_scalar(value: str) -> Any:
    normalized = value.strip().strip('"').strip("'")
    if normalized.lower() in {"true", "false"}:
        return normalized.lower() == "true"
    try:
        return int(normalized)
    except ValueError:
        pass
    try:
        return float(normalized)
    except ValueError:
        return normalized


def load_settings(config_path: Path | None = None) -> Settings:
    selected_path = config_path or Path(os.getenv("RTSP_RECORDER_CONFIG", "config.yaml"))
    raw_config = _read_yaml(selected_path)
    settings = Settings.model_validate(raw_config)
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    settings.recording_path.mkdir(parents=True, exist_ok=True)
    settings.log_path.mkdir(parents=True, exist_ok=True)
    return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
