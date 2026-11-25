from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from app.core.config import Settings
from app.models.domain import Camera
from app.services.camera_service import CameraService
from app.services.event_service import EventService
from app.services.recording_service import RecordingService
from app.services.storage_service import StorageService
from app.workers.camera_worker import CameraWorker, WorkerRuntimeState

logger = logging.getLogger("rtsp_recorder.manager")

SUPERVISOR_INTERVAL_SECONDS = 30.0


class WorkerManager:
    """Creates, starts and stops one CameraWorker per camera.

    It remembers which cameras should be recording. A supervisor thread restarts any of them
    whose worker is not running: a start refused for lack of disk space, a failed restart
    after an edit, or a worker thread that died.
    """

    def __init__(
        self,
        settings: Settings,
        camera_service: CameraService,
        storage_service: StorageService,
        event_service: EventService,
        recording_service: RecordingService,
        free_space: Callable[[], bool] | None = None,
        worker_factory: Callable[..., CameraWorker] = CameraWorker,
    ) -> None:
        self.settings = settings
        self.camera_service = camera_service
        self.storage_service = storage_service
        self.event_service = event_service
        self.recording_service = recording_service
        # called before refusing a start for lack of space: tries to free it (cleanup service)
        self.free_space = free_space or storage_service.has_minimum_free_space
        self.worker_factory = worker_factory
        self._workers: dict[int, CameraWorker] = {}
        self._lock = threading.RLock()
        self._desired: set[int] = set()  # cameras that should be recording
        self._busy: set[int] = set()  # cameras being reconfigured right now
        self._supervisor: threading.Thread | None = None
        self._supervisor_stop = threading.Event()

    def autostart(self) -> None:
        for camera in self.camera_service.list_autostart_cameras():
            try:
                self.start_camera(camera.id)
            except RuntimeError as exc:
                self.event_service.record(
                    "WARNING",
                    f"Autostart delayed for {camera.name}: {exc}; retrying automatically",
                    camera.id,
                )

    def start_camera(self, camera_id: int) -> dict[str, object]:
        camera = self.camera_service.get_camera(camera_id)
        if camera is None:
            raise KeyError(f"Camera {camera_id} not found")
        if not camera.enabled:
            raise RuntimeError(f"Camera {camera.name} is disabled")
        with self._lock:
            # from now on the supervisor keeps trying, even if this attempt is refused
            self._desired.add(camera_id)
        # specification: below the free-space threshold no new recording is started
        if not self.storage_service.has_minimum_free_space() and not self.free_space():
            raise RuntimeError("Disk free space below configured threshold")

        with self._lock:
            worker = self._workers.get(camera_id)
            if worker is None:
                worker = self._create_worker(camera)
                self._workers[camera_id] = worker
            worker.start()
            return worker.status()

    def stop_camera(self, camera_id: int) -> dict[str, object]:
        camera = self.camera_service.get_camera(camera_id)
        if camera is None:
            raise KeyError(f"Camera {camera_id} not found")
        with self._lock:
            self._desired.discard(camera_id)
            worker = self._workers.get(camera_id)
        if worker is None:
            return self._offline_status(camera)
        worker.stop()
        return worker.status()

    def remove_camera(self, camera_id: int) -> None:
        with self._lock:
            self._desired.discard(camera_id)
            worker = self._workers.pop(camera_id, None)
        if worker is not None:
            worker.stop()

    def refresh_camera(self, camera: Camera) -> None:
        """Applies an edited camera: the worker restarts with the new name/URL if it was running."""
        with self._lock:
            worker = self._workers.pop(camera.id, None)
            wanted = camera.id in self._desired
            self._busy.add(camera.id)
        try:
            if worker is not None:
                worker.stop()
            if not camera.enabled:
                with self._lock:
                    self._desired.discard(camera.id)
                return
            if wanted:
                self.start_camera(camera.id)  # if refused, the supervisor retries
        finally:
            with self._lock:
                self._busy.discard(camera.id)

    # --- supervision ---------------------------------------------------------------------

    def supervise_once(self) -> None:
        """Starts every camera that should be recording but whose worker is not running."""
        with self._lock:
            pending = [
                (camera_id, self._workers.get(camera_id))
                for camera_id in self._desired
                if camera_id not in self._busy
            ]
        for camera_id, worker in pending:
            if worker is not None and worker.is_running():
                continue
            camera = self.camera_service.get_camera(camera_id)
            if camera is None or not camera.enabled:
                with self._lock:
                    self._desired.discard(camera_id)
                continue
            if worker is not None:
                # the worker thread ended without being stopped: should never happen
                self.event_service.record(
                    "ERROR", f"Recording worker of {camera.name} had stopped: restarted", camera_id
                )
            # under the lock: a concurrent stop either sees this worker or cancels the start
            with self._lock:
                if camera_id not in self._desired or camera_id in self._busy:
                    continue
                try:
                    self.start_camera(camera_id)
                except (KeyError, RuntimeError) as exc:
                    logger.info("Start of %s still refused: %s", camera.name, exc)

    def start_supervisor(self, interval: float = SUPERVISOR_INTERVAL_SECONDS) -> None:
        if self._supervisor is not None and self._supervisor.is_alive():
            return
        self._supervisor_stop.clear()

        def loop() -> None:
            while not self._supervisor_stop.wait(interval):
                try:
                    self.supervise_once()
                except Exception:  # noqa: BLE001 - the supervisor must survive anything
                    logger.exception("Worker supervision failed")

        self._supervisor = threading.Thread(target=loop, name="worker-supervisor", daemon=True)
        self._supervisor.start()

    def stop_supervisor(self) -> None:
        self._supervisor_stop.set()
        if self._supervisor is not None:
            self._supervisor.join(timeout=10)

    # --- status --------------------------------------------------------------------------

    def status_for_camera(self, camera: Camera) -> dict[str, object]:
        with self._lock:
            worker = self._workers.get(camera.id)
        return worker.status() if worker is not None else self._offline_status(camera)

    def all_statuses(self) -> dict[int, dict[str, object]]:
        return {
            camera.id: self.status_for_camera(camera)
            for camera in self.camera_service.list_cameras()
        }

    def recording_health(self) -> dict[str, int]:
        """How many cameras should be recording and how many actually are."""
        with self._lock:
            desired = list(self._desired)
            workers = dict(self._workers)
        recording = sum(
            1
            for camera_id in desired
            if (worker := workers.get(camera_id)) is not None
            and worker.status()["state"] == "recording"
        )
        return {"expected": len(desired), "recording": recording}

    def active_files(self) -> set[Path]:
        """Segments being written right now: cleanup must never delete them."""
        with self._lock:
            workers = list(self._workers.values())
        return {path.resolve() for worker in workers if (path := worker.active_file()) is not None}

    def shutdown(self) -> None:
        self.stop_supervisor()
        with self._lock:
            workers = list(self._workers.values())
        threads = [threading.Thread(target=worker.stop) for worker in workers]
        for thread in threads:  # stop cameras in parallel: each may wait for ffmpeg
            thread.start()
        for thread in threads:
            thread.join()

    def _create_worker(self, camera: Camera) -> CameraWorker:
        return self.worker_factory(
            camera=camera,
            settings=self.settings,
            storage_service=self.storage_service,
            event_service=self.event_service,
            recording_service=self.recording_service,
        )

    @staticmethod
    def _offline_status(camera: Camera) -> dict[str, object]:
        return {"camera_id": camera.id, "camera_name": camera.name, **asdict(WorkerRuntimeState())}
