"""CameraWorker against a fake ffmpeg (tests/fake_ffmpeg.py): no camera or ffmpeg needed."""

from pathlib import Path

import pytest
from conftest import fake_ffmpeg, wait_until

from app.core.config import Settings
from app.core.database import Database
from app.services.camera_service import CameraService
from app.services.event_service import EventService
from app.services.recording_service import RecordingService
from app.services.storage_service import StorageService
from app.workers.camera_worker import CameraWorker


@pytest.fixture
def make_worker(settings: Settings, database: Database):
    workers: list[CameraWorker] = []
    camera = CameraService(database).create_camera("Gate", "rtsp://admin:s3cret@10.0.0.9/live")

    def make(mode: str, **kwargs) -> CameraWorker:
        worker = CameraWorker(
            camera=camera,
            settings=settings,
            storage_service=StorageService(settings),
            event_service=EventService(database),
            recording_service=RecordingService(database, settings.recording_path),
            probe=lambda _settings, _path: 1.1,
            build_command=fake_ffmpeg(mode, **kwargs),
        )
        workers.append(worker)
        return worker

    yield make
    for worker in workers:
        worker.stop(timeout=5)


def _events(database: Database) -> list[str]:
    return [e.message for e in EventService(database).list_recent(100)][::-1]


def test_recording_goes_online_and_indexes_segments(make_worker, database: Database) -> None:
    worker = make_worker("record", segment_seconds=1.1)
    assert worker.status()["state"] == "stopped"
    worker.start()
    wait_until(lambda: worker.status()["state"] == "recording")
    status = worker.status()
    assert status["online"] and status["recording"] and status["pid"]
    assert status["current_file"].endswith("Z.mkv")  # UTC segment names

    # after a rollover the closed segment is stored with its duration
    recordings = RecordingService(database, Path(status["current_file"]).parent.parent)
    wait_until(lambda: any(r.duration == 1.1 for r in recordings.list_recordings()), timeout=15)
    worker.stop()
    assert worker.status()["state"] == "stopped"
    assert not worker.status()["online"]
    assert all(r.duration is not None for r in recordings.list_recordings())

    events = _events(database)
    assert events.count("Recording started for Gate") == 1
    assert events[-1] == "Recording stopped for Gate"


def test_failing_ffmpeg_backs_off_with_one_event(make_worker, database: Database) -> None:
    worker = make_worker("fail")
    worker.start()
    wait_until(lambda: worker.status()["restart_count"] >= 3)
    status = worker.status()
    assert status["state"] == "reconnecting"
    assert not status["online"]
    assert status["next_retry_at"] is not None
    # ffmpeg's message is shown, without the camera password
    assert "Connection refused" in status["last_error"]
    assert "s3cret" not in status["last_error"]
    warnings = [m for m in _events(database) if m.startswith("Cannot record")]
    assert len(warnings) == 1  # one event per outage, not one per retry

    log_text = worker.ffmpeg_log_path.read_text(encoding="utf-8")
    assert "Connection refused" in log_text and "s3cret" not in log_text


def test_stalled_stream_is_restarted(make_worker) -> None:
    worker = make_worker("stall")
    worker.start()
    wait_until(lambda: worker.status()["restart_count"] >= 1, timeout=15)
    assert "stopped growing" in (worker.status()["last_error"] or "")


def test_missing_ffmpeg_binary(make_worker, settings: Settings, database: Database) -> None:
    worker = CameraWorker(
        camera=CameraService(database).list_cameras()[0],
        settings=settings,
        storage_service=StorageService(settings),
        event_service=EventService(database),
        recording_service=RecordingService(database, settings.recording_path),
        build_command=lambda *_: [str(Path(settings.log_path) / "no-such-ffmpeg")],
    )
    worker.start()
    try:
        wait_until(lambda: worker.status()["restart_count"] >= 1)
        assert "Cannot start ffmpeg" in worker.status()["last_error"]
    finally:
        worker.stop()


def test_outage_does_not_survive_stop_and_start(make_worker, database: Database) -> None:
    worker = make_worker("fail")
    worker.start()
    wait_until(lambda: worker.status()["restart_count"] >= 1)
    worker.stop()
    worker.start()
    assert worker.status()["state"] == "starting"
    wait_until(lambda: len([m for m in _events(database) if m.startswith("Cannot record")]) == 2)


def test_stall_time_does_not_count_as_stable_recording(make_worker) -> None:
    worker = make_worker("record")
    worker._recording_since = 100.0
    worker._last_growth = 110.0  # then the file stopped growing until the watchdog gave up
    assert worker._recorded_for() == 10.0
    worker._recording_since = None
    assert worker._recorded_for() == 0.0
