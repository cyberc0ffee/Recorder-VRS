"""Recording must survive failures around it: database errors, internal errors, an unwritable
log, refused starts and dead worker threads."""

import sqlite3
import subprocess
import sys
from functools import partial
from pathlib import Path

import pytest
from conftest import fake_ffmpeg, wait_until
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.database import Database
from app.models.domain import Camera
from app.services.camera_service import CameraService
from app.services.event_service import EventService
from app.services.recording_service import RecordingService
from app.services.storage_service import StorageService
from app.workers.camera_worker import CameraWorker
from app.workers.ffmpeg import build_ffmpeg_command


@pytest.fixture
def worker(settings: Settings, database: Database):
    camera = CameraService(database).create_camera("Gate", "rtsp://admin:s3cret@10.0.0.9/live")
    worker = CameraWorker(
        camera=camera,
        settings=settings,
        storage_service=StorageService(settings),
        event_service=EventService(database),
        recording_service=RecordingService(database, settings.recording_path),
        probe=lambda _settings, _path: 1.1,
        build_command=fake_ffmpeg("record", segment_seconds=1.1),
    )
    yield worker
    worker.stop(timeout=5)


@pytest.fixture
def recorder(admin: TestClient) -> TestClient:
    admin.app.state.worker_manager.worker_factory = partial(
        CameraWorker, build_command=fake_ffmpeg("record"), probe=lambda _s, _p: 1.1
    )
    return admin


def _camera(client: TestClient, **extra) -> dict:
    body = {"name": "Gate", "rtsp_url": "rtsp://h/live", "autostart": False, **extra}
    return client.post("/api/cameras", json=body).json()


def _state(client: TestClient, camera_id: int) -> str:
    return client.get(f"/api/cameras/{camera_id}").json()["status"]["state"]


def _locked(*_args, **_kwargs):
    raise sqlite3.OperationalError("database is locked")


def test_recording_goes_on_when_the_database_fails(worker: CameraWorker) -> None:
    worker.event_service.record = _locked
    worker.recording_service.index_file = _locked
    worker.recording_service.delete_by_filename = _locked
    worker.start()
    wait_until(lambda: worker.status()["state"] == "recording")
    first = worker.status()["current_file"]
    # segments keep rolling over although nothing can be stored
    wait_until(lambda: worker.status()["current_file"] not in (None, first), timeout=10)
    assert worker.is_running() and worker.status()["restart_count"] == 0


def test_internal_error_restarts_ffmpeg_instead_of_ending_the_worker(
    worker: CameraWorker,
) -> None:
    real_watch = worker._watch
    calls = []

    def flaky_watch(launched_at: float):
        calls.append(launched_at)
        if len(calls) == 1:
            raise RuntimeError("unexpected bug")
        return real_watch(launched_at)

    worker._watch = flaky_watch
    worker.start()
    wait_until(lambda: len(calls) >= 2 and worker.status()["state"] == "recording", timeout=15)
    assert worker.is_running() and worker.status()["restart_count"] == 1


def test_stderr_is_drained_when_the_log_cannot_be_written(worker: CameraWorker) -> None:
    worker.ffmpeg_log_path = worker.settings.log_path  # a directory: every open fails
    # 2 MB of messages: far more than a pipe buffer, ffmpeg would block if nobody read them
    script = "import sys\nfor i in range(20000): sys.stderr.write('x' * 99 + '\\n')"
    process = subprocess.Popen([sys.executable, "-c", script], stderr=subprocess.PIPE)
    worker._pump_stderr(process)
    assert process.wait(timeout=10) == 0
    assert worker.status()["last_ffmpeg_message"] == "x" * 99


def test_ffmpeg_log_rotates_while_ffmpeg_runs(
    worker: CameraWorker, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.workers import camera_worker

    monkeypatch.setattr(camera_worker, "FFMPEG_LOG_MAX_BYTES", 10_000)
    script = "import sys\nfor i in range(1000): sys.stderr.write('y' * 99 + '\\n')"
    process = subprocess.Popen([sys.executable, "-c", script], stderr=subprocess.PIPE)
    worker._pump_stderr(process)
    process.wait(timeout=10)
    assert worker.ffmpeg_log_path.with_suffix(".log.1").exists()
    assert worker.ffmpeg_log_path.stat().st_size <= 10_000 + 200


def test_supervisor_starts_a_camera_refused_for_low_disk(
    recorder: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = recorder.app.state.worker_manager
    camera = _camera(recorder)
    monkeypatch.setattr(manager.storage_service, "has_minimum_free_space", lambda: False)
    monkeypatch.setattr(manager, "free_space", lambda: False)
    assert recorder.post(f"/api/cameras/{camera['id']}/start").status_code == 409
    assert recorder.get("/health/recording").status_code == 503

    monkeypatch.setattr(manager.storage_service, "has_minimum_free_space", lambda: True)
    manager.supervise_once()  # space is back: the camera starts without user action
    wait_until(lambda: _state(recorder, camera["id"]) == "recording")
    health = recorder.get("/health/recording")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "expected": 1, "recording": 1}


def test_supervisor_restarts_a_dead_worker_but_not_a_stopped_one(recorder: TestClient) -> None:
    manager = recorder.app.state.worker_manager
    camera = _camera(recorder)
    recorder.post(f"/api/cameras/{camera['id']}/start")
    wait_until(lambda: _state(recorder, camera["id"]) == "recording")

    # the worker thread ends without anyone stopping the camera
    worker = manager._workers[camera["id"]]
    worker._stop_event.set()
    worker._thread.join(timeout=10)
    assert not worker.is_running()
    manager.supervise_once()
    wait_until(lambda: _state(recorder, camera["id"]) == "recording")
    events = recorder.get("/api/events", params={"camera_id": camera["id"]}).json()
    assert any("had stopped: restarted" in e["message"] for e in events)

    # a camera stopped by the user stays stopped
    recorder.post(f"/api/cameras/{camera['id']}/stop")
    manager.supervise_once()
    assert _state(recorder, camera["id"]) == "stopped"
    assert recorder.get("/health/recording").json()["expected"] == 0


def test_only_video_and_audio_are_recorded(tmp_path: Path) -> None:
    camera = Camera(
        id=1,
        name="Gate",
        rtsp_url="rtsp://h/live",
        enabled=True,
        autostart=True,
        created_at="2026-07-10T00:00:00+00:00",
    )
    command = build_ffmpeg_command(Settings(), camera, tmp_path)
    maps = [command[i + 1] for i, arg in enumerate(command) if arg == "-map"]
    assert maps == ["0:v", "0:a?"]  # no data tracks (ONVIF metadata)
    command = build_ffmpeg_command(Settings(record_audio=False), camera, tmp_path)
    assert [command[i + 1] for i, arg in enumerate(command) if arg == "-map"] == ["0:v"]


def test_segments_are_written_to_disk_packet_by_packet(tmp_path: Path) -> None:
    camera = Camera(
        id=1,
        name="Gate",
        rtsp_url="rtsp://h/live",
        enabled=True,
        autostart=True,
        created_at="2026-07-10T00:00:00+00:00",
    )
    command = build_ffmpeg_command(Settings(), camera, tmp_path)
    options = command[command.index("-segment_format_options") + 1]
    assert options == "flush_packets=1"  # no 256 KB buffer: the watchdog sees steady growth
