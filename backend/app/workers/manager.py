from __future__ import annotations

import threading

from app.core.config import Settings
from app.models.domain import Camera
from app.services.camera_service import CameraService
from app.services.event_service import EventService
from app.services.recording_service import RecordingService
from app.services.storage_service import StorageService
from app.workers.camera_worker import CameraWorker


class WorkerManager:
    def __init__(
        self,
        settings: Settings,
        camera_service: CameraService,
        storage_service: StorageService,
        event_service: EventService,
        recording_service: RecordingService,
    ) -> None:
        self.settings = settings
        self.camera_service = camera_service
        self.storage_service = storage_service
        self.event_service = event_service
        self.recording_service = recording_service
        self._workers: dict[int, CameraWorker] = {}
        self._lock = threading.RLock()

    def autostart(self) -> None:
        for camera in self.camera_service.list_autostart_cameras():
            try:
                self.start_camera(camera.id)
            except RuntimeError as exc:
                self.event_service.record("WARNING", f"Autostart skipped for {camera.name}: {exc}", camera.id)

    def start_camera(self, camera_id: int) -> dict[str, object]:
        camera = self.camera_service.get_camera(camera_id)
        if camera is None:
            raise KeyError(f"Camera {camera_id} not found")
        if not camera.enabled:
            raise RuntimeError(f"Camera {camera.name} is disabled")
        if not self.storage_service.has_minimum_free_space():
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
        with self._lock:
            worker = self._workers.pop(camera.id, None)
        if worker is not None:
            was_recording = bool(worker.status()["recording"])
            worker.stop()
            if was_recording and camera.enabled:
                self.start_camera(camera.id)

    def status_for_camera(self, camera: Camera) -> dict[str, object]:
        with self._lock:
            worker = self._workers.get(camera.id)
            if worker is None:
                return self._offline_status(camera)
            return worker.status()

    def all_statuses(self) -> dict[int, dict[str, object]]:
        statuses: dict[int, dict[str, object]] = {}
        cameras = self.camera_service.list_cameras()
        with self._lock:
            for camera in cameras:
                worker = self._workers.get(camera.id)
                statuses[camera.id] = worker.status() if worker is not None else self._offline_status(camera)
        return statuses

    def shutdown(self) -> None:
        with self._lock:
            workers = list(self._workers.values())
        for worker in workers:
            worker.stop()

    def _create_worker(self, camera: Camera) -> CameraWorker:
        return CameraWorker(
            camera=camera,
            settings=self.settings,
            storage_service=self.storage_service,
            event_service=self.event_service,
            recording_service=self.recording_service,
        )

    @staticmethod
    def _offline_status(camera: Camera) -> dict[str, object]:
        return {
            "camera_id": camera.id,
            "camera_name": camera.name,
            "online": False,
            "recording": False,
            "pid": None,
            "started_at": None,
            "stopped_at": None,
            "restart_count": 0,
            "last_error": None,
            "last_exit_code": None,
            "current_file": None,
            "bytes_written": 0,
            "last_file_growth_at": None,
        }
