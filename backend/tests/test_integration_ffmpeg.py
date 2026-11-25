"""End-to-end recording with the real ffmpeg/ffprobe against a live RTSP stream.

Skipped unless RTSP_TEST_URL is set (the CI starts MediaMTX and publishes a test pattern):

    RTSP_TEST_URL=rtsp://127.0.0.1:8554/test pytest backend/tests/test_integration_ffmpeg.py
"""

import os
import shutil
import subprocess
import time

import pytest
from conftest import wait_until

from app.core.config import Settings
from app.core.database import Database
from app.services.camera_service import CameraService
from app.services.event_service import EventService
from app.services.recording_service import RecordingService
from app.services.storage_service import StorageService
from app.workers.camera_worker import CameraWorker
from app.workers.ffmpeg import build_playback_command

RTSP_TEST_URL = os.getenv("RTSP_TEST_URL")
pytestmark = pytest.mark.skipif(
    not RTSP_TEST_URL or not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="needs RTSP_TEST_URL and ffmpeg/ffprobe on PATH",
)


def test_records_segments_from_a_real_stream(settings: Settings, database: Database) -> None:
    settings = settings.model_copy(
        update={
            "segment_duration_seconds": 2,
            "watchdog_interval_seconds": 0.5,
            "file_stale_seconds": 10,
        }
    )
    camera = CameraService(database).create_camera("Test Pattern", RTSP_TEST_URL)
    recordings = RecordingService(database, settings.recording_path)
    worker = CameraWorker(
        camera, settings, StorageService(settings), EventService(database), recordings
    )
    worker.start()
    try:
        wait_until(lambda: worker.status()["state"] == "recording", timeout=30)
        time.sleep(7)
    finally:
        worker.stop()

    finished = recordings.list_recordings()
    assert len(finished) >= 2
    assert all(r.size > 0 for r in finished)
    assert all(r.duration and 0 < r.duration < 10 for r in finished)

    # browser playback: the remuxed output is MP4
    source = recordings.file_path(finished[-1])
    output = subprocess.run(
        build_playback_command(settings, source), capture_output=True, timeout=30, check=True
    ).stdout
    assert output[4:8] == b"ftyp"


def _publish(url: str) -> subprocess.Popen[bytes]:
    """A camera like most real ones: H.264 video and G.711 audio."""
    return subprocess.Popen(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "warning", "-re",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10",
            "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=8000",
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-g", "10",
            "-c:a", "pcm_mulaw",
            "-f", "rtsp", "-rtsp_transport", "tcp", url,
        ],
        stdin=subprocess.DEVNULL,
    )  # fmt: skip


def _stop(process: subprocess.Popen[bytes]) -> None:
    process.kill()
    process.wait(timeout=10)


def test_recording_resumes_when_the_camera_comes_back(
    settings: Settings, database: Database
) -> None:
    url = RTSP_TEST_URL.rsplit("/", 1)[0] + "/flaky"
    settings = settings.model_copy(
        update={
            "segment_duration_seconds": 3,
            "watchdog_interval_seconds": 0.5,
            "file_stale_seconds": 10,
            "restart_delay_seconds": 1,
            "max_restart_delay_seconds": 2,
            "rtsp_timeout_seconds": 3,
        }
    )
    events = EventService(database)
    recordings = RecordingService(database, settings.recording_path)
    camera = CameraService(database).create_camera("Flaky", url)
    worker = CameraWorker(camera, settings, StorageService(settings), events, recordings)
    publisher = _publish(url)
    worker.start()
    try:
        wait_until(lambda: worker.status()["state"] == "recording", timeout=30)
        time.sleep(4)
        _stop(publisher)  # the camera disappears
        wait_until(lambda: worker.status()["state"] == "reconnecting", timeout=30)
        time.sleep(5)  # several failed attempts while it is away
        publisher = _publish(url)  # ...and comes back
        wait_until(lambda: worker.status()["state"] == "recording", timeout=30)
        time.sleep(4)
    except AssertionError:
        print("worker status:", worker.status())
        if worker.ffmpeg_log_path.exists():
            print(worker.ffmpeg_log_path.read_text(encoding="utf-8")[-4000:])
        for path in sorted(worker.output_dir.glob("*.mkv")):
            print(path.name, path.stat().st_size)
        raise
    finally:
        worker.stop()
        _stop(publisher)

    messages = [e.message for e in events.list_recent(100)]
    assert sum("Recording interrupted" in m for m in messages) == 1  # one event per outage
    assert any("Recording resumed for Flaky" in m for m in messages)
    finished = recordings.list_recordings(camera_id=camera.id)
    assert len(finished) >= 2 and all(r.size > 0 for r in finished)
    # audio is kept: every segment has a video and an audio track
    for recording in finished:
        streams = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
             str(recordings.file_path(recording))],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout.split()  # fmt: skip
        assert sorted(streams) == ["audio", "video"], recording.filename
