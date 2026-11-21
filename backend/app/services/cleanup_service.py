from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import Settings
from app.services.event_service import EventService
from app.services.recording_service import RecordingService
from app.services.storage_service import GB, StorageService

logger = logging.getLogger("rtsp_recorder.cleanup")


@dataclass
class CleanupResult:
    deleted_files: int = 0
    deleted_bytes: int = 0
    deleted_for_space: int = 0
    pruned_database_rows: int = 0
    pruned_events: int = 0
    errors: list[str] = field(default_factory=list)


class CleanupService:
    """Retention by age, recovery of free disk space, pruning of events and sessions.

    Files being written (see `active_files`) are never deleted.
    """

    def __init__(
        self,
        settings: Settings,
        storage_service: StorageService,
        recording_service: RecordingService,
        event_service: EventService,
        active_files: Callable[[], set[Path]] = set,
        purge_sessions: Callable[[], int] | None = None,
    ) -> None:
        self.settings = settings
        self.storage_service = storage_service
        self.recording_service = recording_service
        self.event_service = event_service
        self.active_files = active_files
        self.purge_sessions = purge_sessions
        self._run_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._space_warning_active = False

    # --- single passes -------------------------------------------------------------------

    def _delete(self, path: Path, result: CleanupResult) -> bool:
        try:
            size = path.stat().st_size
            path.unlink()
        except FileNotFoundError:
            self.recording_service.delete_by_filename(str(path))
            return False
        except OSError as exc:
            result.errors.append(f"{path.name}: {exc}")
            return False
        self.recording_service.delete_by_filename(str(path))
        result.deleted_files += 1
        result.deleted_bytes += size
        return True

    def enforce_retention(self, result: CleanupResult) -> None:
        active = self.active_files()
        for path in self.storage_service.old_recording_files():
            if path not in active:
                self._delete(path, result)

    def recover_free_space(self, result: CleanupResult) -> bool:
        """Deletes the oldest recordings until free space is above minimum + margin.

        Returns True if the minimum is satisfied at the end.
        """
        stats = self.storage_service.disk_stats()
        if not stats.below_threshold:
            self._space_warning_active = False
            return True
        target = stats.minimum_free_bytes + int(self.settings.free_disk_margin_gb * GB)
        active = self.active_files()
        files_before, bytes_before = result.deleted_files, result.deleted_bytes
        for _, path in self.storage_service.recording_files():
            if self.storage_service.disk_stats().free_bytes >= target:
                break
            if path not in active and self._delete(path, result):
                result.deleted_for_space += 1

        if result.deleted_files > files_before:
            self.event_service.record(
                "WARNING",
                f"Low disk space: deleted the {result.deleted_files - files_before} oldest "
                f"recordings ({(result.deleted_bytes - bytes_before) // (1024 * 1024)} MB)",
            )
        satisfied = not self.storage_service.disk_stats().below_threshold
        if not satisfied and not self._space_warning_active:
            self.event_service.record(
                "ERROR",
                "Disk free space below the configured minimum and no more recordings can be "
                "deleted: free space on the recording disk",
            )
        self._space_warning_active = not satisfied
        return satisfied

    def ensure_free_space(self) -> bool:
        """Entry point for the worker manager before starting a camera."""
        with self._run_lock:
            return self.recover_free_space(CleanupResult())

    def run_once(self) -> CleanupResult:
        """Full pass: retention, free space, stale database rows, old events and sessions."""
        result = CleanupResult()
        with self._run_lock:
            self.enforce_retention(result)
            self.recover_free_space(result)
            result.pruned_database_rows = self.recording_service.prune_missing_files()
            result.pruned_events = self.event_service.prune(
                self.settings.event_retention_days, self.settings.max_events
            )
            if self.purge_sessions is not None:
                self.purge_sessions()
        if result.deleted_files or result.pruned_database_rows or result.errors:
            self.event_service.record(
                "WARNING" if result.errors else "INFO",
                (
                    f"Cleanup completed: deleted_files={result.deleted_files}, "
                    f"deleted_bytes={result.deleted_bytes}, "
                    f"pruned_rows={result.pruned_database_rows}, errors={len(result.errors)}"
                ),
            )
        return result

    # --- background loop -----------------------------------------------------------------

    def start_background(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="cleanup-service", daemon=True)
        self._thread.start()

    def stop_background(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def _loop(self) -> None:
        last_full_run = float("-inf")  # monotonic() is ~uptime
        while not self._stop_event.is_set():
            try:
                if time.monotonic() - last_full_run >= self.settings.cleanup_interval_seconds:
                    self.run_once()
                    last_full_run = time.monotonic()
                else:
                    self.ensure_free_space()
            except Exception:  # noqa: BLE001 - the loop must survive any single failure
                logger.exception("Cleanup pass failed")
            self._stop_event.wait(self.settings.disk_check_interval_seconds)
