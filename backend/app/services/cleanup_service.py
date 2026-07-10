from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings
from app.services.event_service import EventService
from app.services.recording_service import RecordingService
from app.services.storage_service import StorageService


@dataclass(frozen=True)
class CleanupResult:
    deleted_files: int
    deleted_bytes: int
    pruned_database_rows: int
    errors: list[str]


class CleanupService:
    def __init__(
        self,
        settings: Settings,
        storage_service: StorageService,
        recording_service: RecordingService,
        event_service: EventService,
    ) -> None:
        self.settings = settings
        self.storage_service = storage_service
        self.recording_service = recording_service
        self.event_service = event_service
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self) -> CleanupResult:
        deleted_files = 0
        deleted_bytes = 0
        errors: list[str] = []

        for file_path in self.storage_service.old_recording_files():
            try:
                size = file_path.stat().st_size
                file_path.unlink()
                self.recording_service.delete_by_filename(str(file_path))
                deleted_files += 1
                deleted_bytes += size
            except FileNotFoundError:
                self.recording_service.delete_by_filename(str(file_path))
            except OSError as exc:
                errors.append(f"{file_path}: {exc}")

        pruned_rows = self.recording_service.prune_missing_files()
        if deleted_files or pruned_rows or errors:
            self.event_service.record(
                "INFO" if not errors else "WARNING",
                (
                    f"Cleanup completed: deleted_files={deleted_files}, "
                    f"deleted_bytes={deleted_bytes}, pruned_rows={pruned_rows}, errors={len(errors)}"
                ),
            )

        return CleanupResult(
            deleted_files=deleted_files,
            deleted_bytes=deleted_bytes,
            pruned_database_rows=pruned_rows,
            errors=errors,
        )

    def start_background(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="cleanup-service", daemon=True)
        self._thread.start()

    def stop_background(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop_event.wait(self.settings.cleanup_interval_seconds):
            self.run_once()

