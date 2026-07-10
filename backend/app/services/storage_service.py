from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import Settings
from app.models.domain import Camera
from app.utils.paths import ensure_directory, slugify_filename


@dataclass(frozen=True)
class DiskStats:
    total_bytes: int
    used_bytes: int
    free_bytes: int
    free_percent: float
    minimum_free_bytes: int
    below_threshold: bool


class StorageService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def camera_directory(self, camera: Camera) -> Path:
        return ensure_directory(self.settings.recording_path / slugify_filename(camera.name))

    def disk_stats(self) -> DiskStats:
        usage = shutil.disk_usage(self.settings.recording_path)
        minimum_free_bytes = int(self.settings.minimum_free_disk_gb * 1024 * 1024 * 1024)
        free_percent = (usage.free / usage.total * 100) if usage.total else 0.0
        return DiskStats(
            total_bytes=usage.total,
            used_bytes=usage.used,
            free_bytes=usage.free,
            free_percent=free_percent,
            minimum_free_bytes=minimum_free_bytes,
            below_threshold=usage.free < minimum_free_bytes,
        )

    def has_minimum_free_space(self) -> bool:
        return not self.disk_stats().below_threshold

    def old_recording_files(self) -> list[Path]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.settings.retention_days)
        old_files: list[Path] = []
        for file_path in self.settings.recording_path.rglob("*.mkv"):
            try:
                modified_at = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)
            except FileNotFoundError:
                continue
            if modified_at < cutoff:
                old_files.append(file_path)
        return old_files

