from __future__ import annotations

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


class WorkerManager:
    """Creates, starts and stops one CameraWorker per camera."""

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

    def autostart(self) -> None:
        for camera in self.camera_service.list_autostart_cameras():
            try:
                self.start_camera(camera.id)
            except RuntimeError as exc:
                self.event_service.record(
                    "WARNING", f"Autostart skipped for {camera.name}: {exc}", camera.id
                )

    def start_camera(self, camera_id: int) -> dict[str, object]:
        camera = self.camera_service.get_camera(camera_id)
        if camera is None:
            raise KeyError(f"Camera {camera_id} not found")
        if not camera.enabled:
            raise RuntimeError(f"Camera {camera.name} is disabled")
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
            worker = self._workers.get(camera_id)
        if worker is None:
            return self._offline_status(camera)
        worker.stop()
        return worker.status()

    def remove_camera(self, camera_id: int) -> None:
        with self._lock:
            worker = self._workers.pop(camera_id, None)
        if worker is not None:
            worker.stop()

    def refresh_camera(self, camera: Camera) -> None:
        """Applies an edited camera: the worker restarts with the new name/URL if it was running."""
        with self._lock:
            worker = self._workers.pop(camera.id, None)
        if worker is None:
            return
        was_running = worker.is_running()
        worker.stop()
        if was_running and camera.enabled:
            self.start_camera(camera.id)

    def status_for_camera(self, camera: Camera) -> dict[str, object]:
        with self._lock:
            worker = self._workers.get(camera.id)
        return worker.status() if worker is not None else self._offline_status(camera)

    def all_statuses(self) -> dict[int, dict[str, object]]:
        return {
            camera.id: self.status_for_camera(camera)
            for camera in self.camera_service.list_cameras()
        }

    def active_files(self) -> set[Path]:
        """Segments being written right now: cleanup must never delete them."""
        with self._lock:
            workers = list(self._workers.values())
        return {path.resolve() for worker in workers if (path := worker.active_file()) is not None}

    def shutdown(self) -> None:
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
