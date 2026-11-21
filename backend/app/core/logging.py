from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.core.security import redact


class JsonFormatter(logging.Formatter):
    """JSON log lines; URL credentials are always removed from the message."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        for key, value in getattr(record, "extra_fields", {}).items():
            payload[key] = value
        return json.dumps(payload, ensure_ascii=True)


def configure_logging(settings: Settings) -> None:
    settings.log_path.mkdir(parents=True, exist_ok=True)
    log_level = getattr(logging, settings.logging_level.upper(), logging.INFO)

    formatter = JsonFormatter()
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        settings.log_path / "app.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(log_level)
    root_logger.addHandler(stream_handler)
    root_logger.addHandler(file_handler)


def get_camera_log_path(log_path: Path, camera_name: str) -> Path:
    safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in camera_name)
    camera_log_dir = log_path / safe_name
    camera_log_dir.mkdir(parents=True, exist_ok=True)
    return camera_log_dir / "ffmpeg.log"
