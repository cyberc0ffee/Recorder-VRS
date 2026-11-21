from __future__ import annotations

import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, prepare_directories
from app.core.database import Database
from app.main import create_app

FAKE_FFMPEG = Path(__file__).with_name("fake_ffmpeg.py")
ADMIN_PASSWORD = "correct-horse-battery"
CSRF = {"X-Requested-With": "rtsp-recorder"}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings(
        database_path=tmp_path / "data" / "test.sqlite3",
        recording_path=tmp_path / "recordings",
        log_path=tmp_path / "logs",
        minimum_free_disk_gb=0,
        free_disk_margin_gb=0,
        watchdog_interval_seconds=0.1,
        file_stale_seconds=1.0,
        restart_delay_seconds=0.2,
        max_restart_delay_seconds=0.8,
        cleanup_interval_seconds=3600,
        disk_check_interval_seconds=3600,
    ).resolved()
    prepare_directories(s)
    return s


@pytest.fixture
def database(settings: Settings) -> Iterator[Database]:
    db = Database(settings.database_path)
    db.init_schema()
    yield db
    db.close()


@pytest.fixture
def frontend_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app shell</html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    return dist


@pytest.fixture
def client(
    settings: Settings, frontend_dist: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setenv("RTSP_RECORDER_ADMIN_PASSWORD", ADMIN_PASSWORD)
    with TestClient(create_app(settings, frontend_dist=frontend_dist)) as test_client:
        yield test_client


@pytest.fixture
def admin(client: TestClient) -> TestClient:
    response = client.post(
        "/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}, headers=CSRF
    )
    assert response.status_code == 200, response.text
    client.headers.update(CSRF)
    return client


def fake_ffmpeg(mode: str, segment_seconds: float = 1.1) -> Callable[..., list[str]]:
    from app.workers.ffmpeg import build_segment_pattern

    def build(settings: Settings, camera, output_dir: Path) -> list[str]:
        pattern = str(build_segment_pattern(camera, output_dir))
        return [sys.executable, str(FAKE_FFMPEG), mode, pattern, str(segment_seconds)]

    return build


def wait_until(condition: Callable[[], bool], timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError("condition not reached in time")
