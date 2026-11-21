from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from app.core.config import Settings
from app.services.camera_service import CameraService
from app.services.recording_service import RecordingService
from app.services.storage_service import StorageService
from app.workers.ffmpeg import probe_duration

logger = logging.getLogger("rtsp_recorder.reconcile")
# files modified more recently than this may still be open: their duration is read later
SETTLE_SECONDS = 30


class ReconcileService:
    """Aligns the database with the files on disk at startup.

    Segments written while the database was unavailable are indexed, rows of deleted files
    are removed, and missing durations are read with ffprobe in the background.
    """

    def __init__(
        self,
        settings: Settings,
        camera_service: CameraService,
        storage_service: StorageService,
        recording_service: RecordingService,
        active_files: Callable[[], set[Path]] = set,
        probe: Callable[[Settings, Path], float | None] = probe_duration,
    ) -> None:
        self.settings = settings
        self.camera_service = camera_service
        self.storage_service = storage_service
        self.recording_service = recording_service
        self.active_files = active_files
        self.probe = probe
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def index_existing_files(self) -> int:
        known = self.recording_service.known_filenames()
        added = 0
        for camera in self.camera_service.list_cameras():
            for path in self.storage_service.camera_directory(camera).glob("*.mkv"):
                if str(path.resolve()) not in known:
                    self.recording_service.index_file(camera.id, path)
                    added += 1
        return added

    def probe_missing_durations(self) -> int:
        probed = 0
        active = self.active_files()
        for recording in self.recording_service.without_duration():
            if self._stop_event.is_set():
                break
            path = self.recording_service.file_path(recording)
            if path is None or path in active:
                continue
            try:
                if time.time() - path.stat().st_mtime < SETTLE_SECONDS:
                    continue
            except OSError:
                continue
            duration = self.probe(self.settings, path)
            if duration is not None:
                self.recording_service.index_file(recording.camera_id, path, duration)
                probed += 1
        return probed

    def run(self) -> None:
        migrated = self.recording_service.migrate_relative_paths(Path.cwd())
        pruned = self.recording_service.prune_missing_files()
        added = self.index_existing_files()
        if migrated or pruned or added:
            logger.info(
                "Recordings reconciled: %d paths migrated, %d stale rows removed, %d files added",
                migrated,
                pruned,
                added,
            )

    def start_background_probe(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._probe_safely, name="duration-probe", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=25)

    def _probe_safely(self) -> None:
        try:
            probed = self.probe_missing_durations()
            if probed:
                logger.info("Durations read for %d recordings", probed)
        except Exception:  # noqa: BLE001 - background helper, must not crash the app
            logger.exception("Reading recording durations failed")
