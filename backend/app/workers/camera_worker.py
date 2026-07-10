from __future__ import annotations

import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import IO
from urllib.parse import urlparse

from app.core.config import Settings
from app.core.logging import get_camera_log_path
from app.models.domain import Camera
from app.services.event_service import EventService
from app.services.recording_service import RecordingService
from app.services.storage_service import StorageService
from app.workers.ffmpeg import build_ffmpeg_command, latest_segment


@dataclass
class WorkerRuntimeState:
    online: bool = False
    recording: bool = False
    pid: int | None = None
    started_at: str | None = None
    stopped_at: str | None = None
    restart_count: int = 0
    last_error: str | None = None
    last_exit_code: int | None = None
    current_file: str | None = None
    bytes_written: int = 0
    last_file_growth_at: str | None = None


class CameraWorker:
    """Owns the ffmpeg process and watchdog for one camera."""

    def __init__(
        self,
        camera: Camera,
        settings: Settings,
        storage_service: StorageService,
        event_service: EventService,
        recording_service: RecordingService,
    ) -> None:
        self.camera = camera
        self.settings = settings
        self.storage_service = storage_service
        self.event_service = event_service
        self.recording_service = recording_service
        self.output_dir = self.storage_service.camera_directory(camera)
        self.ffmpeg_log_path = get_camera_log_path(settings.log_path, camera.name)
        self._state = WorkerRuntimeState()
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._stderr_file: IO[bytes] | None = None
        self._last_known_size = 0
        self._last_growth_monotonic = time.monotonic()
        self._last_rtsp_check = 0.0
        self._last_disk_warning = 0.0

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            if not self.storage_service.has_minimum_free_space():
                message = f"Not starting camera {self.camera.name}: disk free space below threshold"
                self._state.last_error = message
                self.event_service.record("WARNING", message, self.camera.id)
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name=f"camera-worker-{self.camera.id}",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop_event.set()
        self._terminate_process(timeout=timeout)
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        with self._lock:
            self._state.online = False
            self._state.recording = False
            self._state.pid = None
            self._state.stopped_at = datetime.now(timezone.utc).isoformat()

    def status(self) -> dict[str, object]:
        with self._lock:
            return {
                "camera_id": self.camera.id,
                "camera_name": self.camera.name,
                "online": self._state.online,
                "recording": self._state.recording,
                "pid": self._state.pid,
                "started_at": self._state.started_at,
                "stopped_at": self._state.stopped_at,
                "restart_count": self._state.restart_count,
                "last_error": self._state.last_error,
                "last_exit_code": self._state.last_exit_code,
                "current_file": self._state.current_file,
                "bytes_written": self._state.bytes_written,
                "last_file_growth_at": self._state.last_file_growth_at,
            }

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._launch_process()
            while not self._stop_event.wait(self.settings.watchdog_interval_seconds):
                if self._process is None:
                    break

                exit_code = self._process.poll()
                if exit_code is not None:
                    self._handle_process_exit(exit_code)
                    break

                self._check_disk_pressure()
                self._check_rtsp_reachable()
                should_restart = self._check_file_growth()
                if should_restart:
                    self._terminate_process(timeout=5.0)
                    break

            if not self._stop_event.is_set():
                self._sleep_before_restart()

        self._terminate_process(timeout=5.0)

    def _launch_process(self) -> None:
        command = build_ffmpeg_command(self.settings, self.camera, self.output_dir)
        self.ffmpeg_log_path.parent.mkdir(parents=True, exist_ok=True)
        self._stderr_file = self.ffmpeg_log_path.open("ab")
        try:
            self._process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=self._stderr_file,
            )
        except OSError as exc:
            self._close_stderr()
            with self._lock:
                self._state.online = False
                self._state.recording = False
                self._state.pid = None
                self._state.last_error = str(exc)
            self.event_service.record("ERROR", f"Failed to start ffmpeg for {self.camera.name}: {exc}", self.camera.id)
            return

        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._state.online = True
            self._state.recording = True
            self._state.pid = self._process.pid
            self._state.started_at = now
            self._state.stopped_at = None
            self._state.last_error = None
        self._last_growth_monotonic = time.monotonic()
        self.event_service.record("INFO", f"Started recording camera {self.camera.name}", self.camera.id)

    def _handle_process_exit(self, exit_code: int) -> None:
        self._close_stderr()
        with self._lock:
            self._state.online = False
            self._state.recording = False
            self._state.pid = None
            self._state.last_exit_code = exit_code
            self._state.last_error = f"ffmpeg exited with code {exit_code}"
        self.event_service.record(
            "WARNING",
            f"ffmpeg exited for camera {self.camera.name} with code {exit_code}",
            self.camera.id,
        )

    def _check_file_growth(self) -> bool:
        newest_file = latest_segment(self.output_dir)
        if newest_file is None:
            stale_for = time.monotonic() - self._last_growth_monotonic
            if stale_for > self.settings.file_stale_seconds:
                message = f"No MKV segment created for camera {self.camera.name} after {int(stale_for)} seconds"
                self._mark_stale(message)
                return True
            return False

        try:
            current_size = newest_file.stat().st_size
        except FileNotFoundError:
            return False

        if str(newest_file) != self._state.current_file or current_size > self._last_known_size:
            self._last_known_size = current_size
            self._last_growth_monotonic = time.monotonic()
            now = datetime.now(timezone.utc).isoformat()
            with self._lock:
                self._state.current_file = str(newest_file)
                self._state.bytes_written = current_size
                self._state.last_file_growth_at = now
            self.recording_service.index_file(self.camera.id, newest_file)
            return False

        stale_for = time.monotonic() - self._last_growth_monotonic
        if stale_for > self.settings.file_stale_seconds:
            message = f"Recording file stopped growing for camera {self.camera.name} after {int(stale_for)} seconds"
            self._mark_stale(message)
            return True
        return False

    def _mark_stale(self, message: str) -> None:
        with self._lock:
            self._state.last_error = message
        self.event_service.record("WARNING", message, self.camera.id)

    def _check_disk_pressure(self) -> None:
        if self.storage_service.has_minimum_free_space():
            return
        now = time.monotonic()
        if now - self._last_disk_warning < 60:
            return
        self._last_disk_warning = now
        self.event_service.record(
            "WARNING",
            f"Disk free space below threshold while recording camera {self.camera.name}",
            self.camera.id,
        )

    def _check_rtsp_reachable(self) -> None:
        now = time.monotonic()
        if now - self._last_rtsp_check < 30:
            return
        self._last_rtsp_check = now

        parsed = urlparse(self.camera.rtsp_url)
        if not parsed.hostname:
            return
        port = parsed.port or 554
        try:
            with socket.create_connection((parsed.hostname, port), timeout=3):
                return
        except OSError as exc:
            with self._lock:
                self._state.last_error = f"RTSP endpoint unreachable: {exc}"
            self.event_service.record(
                "WARNING",
                f"RTSP endpoint unreachable for camera {self.camera.name}: {exc}",
                self.camera.id,
            )

    def _sleep_before_restart(self) -> None:
        with self._lock:
            self._state.restart_count += 1
        self.event_service.record(
            "INFO",
            f"Restarting camera {self.camera.name} in {self.settings.restart_delay_seconds} seconds",
            self.camera.id,
        )
        self._stop_event.wait(self.settings.restart_delay_seconds)

    def _terminate_process(self, timeout: float) -> None:
        process = self._process
        if process is None:
            self._close_stderr()
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=timeout)
        self._process = None
        self._close_stderr()

    def _close_stderr(self) -> None:
        if self._stderr_file is not None:
            self._stderr_file.close()
            self._stderr_file = None

