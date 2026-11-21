from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import Settings
from app.models.domain import Camera
from app.utils.paths import ensure_directory, slugify_filename

GB = 1024**3


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
        minimum_free_bytes = int(self.settings.minimum_free_disk_gb * GB)
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

    def recording_files(self) -> list[tuple[float, Path]]:
        """(mtime, path) of every recording, oldest first."""
        files: list[tuple[float, Path]] = []
        for path in self.settings.recording_path.rglob("*.mkv"):
            try:
                files.append((path.stat().st_mtime, path.resolve()))
            except OSError:
                continue
        return sorted(files)

    def old_recording_files(self) -> list[Path]:
        cutoff = (datetime.now(UTC) - timedelta(days=self.settings.retention_days)).timestamp()
        return [path for mtime, path in self.recording_files() if mtime < cutoff]
