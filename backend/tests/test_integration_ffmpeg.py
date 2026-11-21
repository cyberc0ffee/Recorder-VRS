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
