from __future__ import annotations

import logging
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import Settings
from app.core.logging import get_camera_log_path
from app.core.security import redact
from app.models.domain import Camera
from app.services.event_service import EventService
from app.services.recording_service import RecordingService
from app.services.storage_service import StorageService
from app.workers.ffmpeg import (
    build_ffmpeg_command,
    latest_segment,
    probe_duration,
    recorder_environment,
)

CommandBuilder = Callable[[Settings, Camera, Path], list[str]]

logger = logging.getLogger("rtsp_recorder.worker")

# a run that recorded for this long resets the restart delay to its minimum
STABLE_RUN_SECONDS = 60.0
# the current segment is written to the database at most this often while it grows
INDEX_INTERVAL_SECONDS = 60.0
FFMPEG_LOG_MAX_BYTES = 5 * 1024 * 1024


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class WorkerRuntimeState:
    # stopped | starting | recording | reconnecting
    state: str = "stopped"
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
    next_retry_at: str | None = None
    last_ffmpeg_message: str | None = None


class CameraWorker:
    """Owns the ffmpeg process and the watchdog of one camera.

    The camera is "online" only while its segment file is actually growing. Failed
    restarts back off exponentially and produce one event per outage, not one per attempt.
    """

    def __init__(
        self,
        camera: Camera,
        settings: Settings,
        storage_service: StorageService,
        event_service: EventService,
        recording_service: RecordingService,
        probe: Callable[[Settings, Path], float | None] = probe_duration,
        build_command: CommandBuilder = build_ffmpeg_command,
    ) -> None:
        self.camera = camera
        self.settings = settings
        self.storage_service = storage_service
        self.event_service = event_service
        self.recording_service = recording_service
        self.probe = probe
        self.build_command = build_command
        self.output_dir = storage_service.camera_directory(camera)
        self.ffmpeg_log_path = get_camera_log_path(settings.log_path, camera.name)
        self._state = WorkerRuntimeState()
        self._lock = threading.RLock()
        self._process_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._stderr_thread: threading.Thread | None = None
        self._last_known_size = 0
        self._last_growth = time.monotonic()
        self._last_index = float("-inf")
        self._recording_since: float | None = None
        self._in_outage = False
        self._outage_started: float | None = None

    # --- public API ----------------------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._in_outage = False
            self._outage_started = None
            self._state.state = "starting"
            self._state.started_at = _now()
            self._state.stopped_at = None
            self._state.next_retry_at = None
            self._thread = threading.Thread(
                target=self._run, name=f"camera-worker-{self.camera.id}", daemon=True
            )
            self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        was_running = self.is_running()
        self._stop_event.set()
        self._terminate_process(timeout=timeout)
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout + 25)  # the thread may be probing the last segment
        with self._lock:
            self._state.state = "stopped"
            self._state.online = False
            self._state.recording = False
            self._state.pid = None
            self._state.next_retry_at = None
            self._state.stopped_at = _now()
        if was_running:
            self.event_service.record(
                "INFO", f"Recording stopped for {self.camera.name}", self.camera.id
            )

    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def status(self) -> dict[str, object]:
        with self._lock:
            return {
                "camera_id": self.camera.id,
                "camera_name": self.camera.name,
                **asdict(self._state),
            }

    def active_file(self) -> Path | None:
        with self._lock:
            return Path(self._state.current_file) if self._state.current_file else None

    # --- main loop -----------------------------------------------------------------------

    def _run(self) -> None:
        delay = float(self.settings.restart_delay_seconds)
        while not self._stop_event.is_set():
            launched_at = time.time()
            reason = self._watch(launched_at) if self._launch_process() else self._state.last_error
            recorded_for = self._recorded_for()
            self._finalize_current_file()
            if self._stop_event.is_set():
                break

            if recorded_for >= STABLE_RUN_SECONDS:
                delay = float(self.settings.restart_delay_seconds)
            self._report_failure(reason or "ffmpeg stopped", recorded_for > 0)
            retry_at = datetime.now(UTC) + timedelta(seconds=delay)
            with self._lock:
                self._state.state = "reconnecting"
                self._state.online = False
                self._state.recording = False
                self._state.pid = None
                self._state.restart_count += 1
                self._state.next_retry_at = retry_at.isoformat()
            logger.info("Restarting %s in %.0f s: %s", self.camera.name, delay, reason)
            self._stop_event.wait(delay)
            delay = min(delay * 2, float(self.settings.max_restart_delay_seconds))

        self._terminate_process(timeout=5.0)
        self._finalize_current_file()

    def _launch_process(self) -> bool:
        command = self.build_command(self.settings, self.camera, self.output_dir)
        self._rotate_ffmpeg_log()
        with self._process_lock:
            if self._stop_event.is_set():
                return False
            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    env=recorder_environment(),
                )
            except OSError as exc:
                with self._lock:
                    self._state.last_error = f"Cannot start ffmpeg: {exc}"
                return False
            self._process = process

        self._stderr_thread = threading.Thread(
            target=self._pump_stderr,
            args=(process,),
            name=f"ffmpeg-log-{self.camera.id}",
            daemon=True,
        )
        self._stderr_thread.start()
        with self._lock:
            self._state.state = "reconnecting" if self._in_outage else "starting"
            self._state.pid = process.pid
            self._state.next_retry_at = None
        self._last_growth = time.monotonic()
        self._last_known_size = 0
        self._recording_since = None
        return True

    def _watch(self, launched_at: float) -> str | None:
        """Watches ffmpeg until it exits, stalls or the worker is stopped (returns None)."""
        while not self._stop_event.wait(self.settings.watchdog_interval_seconds):
            process = self._process
            if process is None:
                return "ffmpeg not running"
            exit_code = process.poll()
            if exit_code is not None:
                self._join_stderr()
                with self._lock:
                    self._state.last_exit_code = exit_code
                    detail = self._state.last_ffmpeg_message
                return f"ffmpeg exited with code {exit_code}" + (f": {detail}" if detail else "")
            stale_reason = self._check_file_growth(launched_at)
            if stale_reason:
                self._terminate_process(timeout=5.0)
                return stale_reason
        return None

    # --- watchdog checks -----------------------------------------------------------------

    def _check_file_growth(self, launched_at: float) -> str | None:
        # files from previous runs do not count as progress of this one
        newest = latest_segment(self.output_dir, since=launched_at - 2)
        stale_for = time.monotonic() - self._last_growth
        if newest is None:
            if stale_for > self.settings.file_stale_seconds:
                return f"No segment created after {int(stale_for)} s"
            return None

        try:
            size = newest.stat().st_size
        except OSError:
            return None

        current = self.active_file()
        if current is None or newest.resolve() != current.resolve():
            self._finalize_current_file()
            with self._lock:
                self._state.current_file = str(newest.resolve())
            self._last_known_size = 0  # a just-created empty file is not progress yet
            self._last_index = float("-inf")

        if size > self._last_known_size:
            self._last_known_size = size
            self._last_growth = time.monotonic()
            with self._lock:
                self._state.bytes_written = size
                self._state.last_file_growth_at = _now()
            self._mark_recording()
            if time.monotonic() - self._last_index >= INDEX_INTERVAL_SECONDS:
                self.recording_service.index_file(self.camera.id, newest)
                self._last_index = time.monotonic()
            return None

        if stale_for > self.settings.file_stale_seconds:
            return f"Recording file stopped growing for {int(stale_for)} s"
        return None

    def _mark_recording(self) -> None:
        with self._lock:
            already = self._state.state == "recording"
            self._state.state = "recording"
            self._state.online = True
            self._state.recording = True
            self._state.last_error = None
        if already:
            return
        self._recording_since = time.monotonic()
        if self._in_outage:
            down_for = int(time.monotonic() - (self._outage_started or time.monotonic()))
            self.event_service.record(
                "INFO",
                f"Recording resumed for {self.camera.name} after {down_for} s",
                self.camera.id,
            )
        else:
            self.event_service.record(
                "INFO", f"Recording started for {self.camera.name}", self.camera.id
            )
        self._in_outage = False
        self._outage_started = None

    def _report_failure(self, reason: str, was_recording: bool) -> None:
        reason = redact(reason)
        with self._lock:
            self._state.last_error = reason
        if self._in_outage:
            return  # already reported: no event for every retry
        self._in_outage = True
        self._outage_started = time.monotonic()
        prefix = "Recording interrupted" if was_recording else "Cannot record"
        self.event_service.record(
            "WARNING", f"{prefix} for {self.camera.name}: {reason}; retrying", self.camera.id
        )

    def _recorded_for(self) -> float:
        # until the last growth: the stale period before the watchdog kills ffmpeg is not recording
        if self._recording_since is None:
            return 0.0
        return max(0.0, self._last_growth - self._recording_since)

    def _finalize_current_file(self) -> None:
        """Writes size and duration of the segment that has just been closed."""
        current = self.active_file()
        if current is None:
            return
        with self._lock:
            self._state.current_file = None
        try:
            empty = current.stat().st_size == 0
        except OSError:
            return
        if empty:
            # segment opened just before ffmpeg stopped: nothing to keep
            current.unlink(missing_ok=True)
            self.recording_service.delete_by_filename(str(current.resolve()))
            return
        if current.exists():
            self.recording_service.index_file(
                self.camera.id, current, self.probe(self.settings, current)
            )

    # --- process and log handling --------------------------------------------------------

    def _pump_stderr(self, process: subprocess.Popen[bytes]) -> None:
        """Copies ffmpeg output to the camera log, without credentials."""
        if process.stderr is None:
            return
        with self.ffmpeg_log_path.open("ab") as log_file:
            for raw_line in process.stderr:
                line = redact(raw_line.decode("utf-8", "replace")).strip()
                if not line:
                    continue
                log_file.write(f"{_now()} {line}\n".encode())
                log_file.flush()
                with self._lock:
                    self._state.last_ffmpeg_message = line[:500]

    def _join_stderr(self) -> None:
        thread = self._stderr_thread
        if thread is not None:
            thread.join(timeout=2)

    def _rotate_ffmpeg_log(self) -> None:
        try:
            if self.ffmpeg_log_path.stat().st_size > FFMPEG_LOG_MAX_BYTES:
                self.ffmpeg_log_path.replace(self.ffmpeg_log_path.with_suffix(".log.1"))
        except OSError:
            pass

    def _terminate_process(self, timeout: float) -> None:
        with self._process_lock:
            process, self._process = self._process, None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()  # SIGTERM: ffmpeg closes the current segment cleanly
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=timeout)
        self._join_stderr()
        if process.stderr is not None:
            process.stderr.close()
