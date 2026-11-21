import sys
from functools import partial
from pathlib import Path

import pytest
from conftest import fake_ffmpeg, wait_until
from fastapi.testclient import TestClient

from app import cli
from app.core.config import load_settings
from app.services import playback_service
from app.workers.camera_worker import CameraWorker


@pytest.fixture
def recorder(admin: TestClient) -> TestClient:
    admin.app.state.worker_manager.worker_factory = partial(
        CameraWorker, build_command=fake_ffmpeg("record"), probe=lambda _s, _p: 1.1
    )
    return admin


def _camera(client: TestClient, name: str = "Gate", **extra) -> dict:
    body = {"name": name, "rtsp_url": "rtsp://admin:pw@10.0.0.9/live", "autostart": False, **extra}
    response = client.post("/api/cameras", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _state(client: TestClient, camera_id: int) -> str:
    return client.get(f"/api/cameras/{camera_id}").json()["status"]["state"]


def test_start_stop_and_system(recorder: TestClient) -> None:
    camera = _camera(recorder)
    assert recorder.post(f"/api/cameras/{camera['id']}/start").status_code == 200
    wait_until(lambda: _state(recorder, camera["id"]) == "recording")

    system = recorder.get("/api/system").json()
    assert system["recording_cameras"] == 1 and system["cameras_online"] == 1
    assert system["disk"]["total_bytes"] > 0

    assert recorder.post(f"/api/cameras/{camera['id']}/stop").json()["state"] == "stopped"
    events = recorder.get("/api/events", params={"camera_id": camera["id"]}).json()
    assert {e["message"] for e in events} >= {
        "Recording started for Gate",
        "Recording stopped for Gate",
    }


def test_autostart_and_rename_restarts_worker(recorder: TestClient) -> None:
    camera = _camera(recorder, autostart=True)
    wait_until(lambda: _state(recorder, camera["id"]) == "recording")
    renamed = recorder.put(f"/api/cameras/{camera['id']}", json={"name": "Gate North"})
    assert renamed.status_code == 200
    wait_until(lambda: _state(recorder, camera["id"]) == "recording")
    status = recorder.get(f"/api/cameras/{camera['id']}").json()["status"]
    assert "Gate_North" in status["current_file"]


def test_disabled_camera_cannot_start(recorder: TestClient) -> None:
    camera = _camera(recorder, enabled=False)
    assert recorder.post(f"/api/cameras/{camera['id']}/start").status_code == 409
    assert recorder.post("/api/cameras/999/start").status_code == 404
    assert recorder.post("/api/cameras/999/stop").status_code == 404
    assert recorder.get("/api/cameras/999").status_code == 404


def test_camera_validation(recorder: TestClient) -> None:
    bad = recorder.post("/api/cameras", json={"name": "X", "rtsp_url": "file:///etc/passwd"})
    assert bad.status_code == 422
    _camera(recorder)
    assert (
        recorder.post("/api/cameras", json={"name": "Gate", "rtsp_url": "rtsp://h/x"}).status_code
        == 409
    )


def test_playback_remux_is_streamed(
    admin: TestClient, settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    camera = _camera(admin)
    path = settings.recording_path / "Gate" / "Gate_2026-07-10_14-15-00.mkv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"mkv")
    admin.app.state.recording_service.index_file(camera["id"], path, 900)
    recording = admin.get("/api/recordings").json()[0]

    # stand-in for ffmpeg: writes 200 kB to stdout
    script = "import sys; sys.stdout.buffer.write(b'm' * 200_000)"
    monkeypatch.setattr(
        playback_service, "build_playback_command", lambda _s, _p: [sys.executable, "-c", script]
    )
    response = admin.get(f"/api/recordings/{recording['id']}/play")
    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
    assert len(response.content) == 200_000


def test_playback_slot_is_released_when_stream_is_never_started(
    settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import gc

    script = "import sys\nwhile True: sys.stdout.buffer.write(b'm' * 65536)"
    monkeypatch.setattr(
        playback_service, "build_playback_command", lambda _s, _p: [sys.executable, "-c", script]
    )
    service = playback_service.PlaybackService(settings, max_concurrent=1)
    stream = service.stream_mp4(tmp_path / "x.mkv")
    process = stream._process
    with pytest.raises(playback_service.PlaybackBusyError):
        service.stream_mp4(tmp_path / "x.mkv")
    del stream  # the client went away before the first chunk
    gc.collect()
    assert process.poll() is not None  # ffmpeg was killed
    second = service.stream_mp4(tmp_path / "x.mkv")  # the slot is free again
    assert next(second)
    second.close()
    second.close()  # idempotent: the slot is released once


def test_settings_from_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("retention_days: 7\nrecording_path: rec\nrestart_delay_seconds: 2.5\n")
    monkeypatch.chdir(tmp_path)
    settings = load_settings(config)
    assert settings.retention_days == 7 and settings.restart_delay_seconds == 2.5
    assert (
        settings.recording_path == (tmp_path / "rec").resolve() and settings.recording_path.is_dir()
    )
    config.write_text("retention_days: 0\n")
    with pytest.raises(ValueError):
        load_settings(config)


def test_cli_set_password(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        f"database_path: {tmp_path / 'db.sqlite3'}\nlog_path: {tmp_path / 'logs'}\n"
        f"recording_path: {tmp_path / 'rec'}\n"
    )
    monkeypatch.setenv("RTSP_RECORDER_CONFIG", str(config))
    answers = iter(["a-new-long-password", "a-new-long-password"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: next(answers))
    assert cli.main(["set-password"]) == 0

    answers = iter(["short", "short"])
    assert cli.main(["set-password"]) == 1
    answers = iter(["one-long-password", "other-long-password"])
    assert cli.main(["set-password"]) == 1

    # a missing configuration is an error: the password must not go to another database
    monkeypatch.chdir(tmp_path)
    missing = tmp_path / "missing.yaml"
    assert cli.main(["--config", str(missing), "set-password"]) == 1
    assert not (tmp_path / "data").exists()
