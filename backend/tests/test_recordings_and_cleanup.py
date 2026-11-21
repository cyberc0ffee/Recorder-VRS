import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import CSRF
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.database import Database
from app.services.camera_service import CameraService
from app.services.cleanup_service import CleanupResult, CleanupService
from app.services.event_service import EventService
from app.services.reconcile_service import ReconcileService
from app.services.recording_service import RecordingService, parse_segment_start
from app.services.storage_service import DiskStats, StorageService


def _segment(directory: Path, name: str, size: int = 1000, age_days: float = 0) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(b"\0" * size)
    if age_days:
        old = time.time() - age_days * 86400
        os.utime(path, (old, old))
    return path


def test_segment_names_utc_and_legacy_local_time() -> None:
    # current names are UTC: the repeated hour at the end of daylight saving gets distinct names
    first = parse_segment_start("Gate_2026-10-25_00-15-00Z.mkv")
    second = parse_segment_start("Gate_2026-10-25_01-15-00Z.mkv")
    assert first == datetime(2026, 10, 25, 0, 15, tzinfo=UTC)
    assert second - first == timedelta(hours=1)
    # names written by 0.1 carry the server's local time
    start = parse_segment_start("Gate_2026-07-10_14-15-00.mkv")
    expected = datetime(2026, 7, 10, 14, 15).astimezone(UTC)
    assert start == expected and start.tzinfo == UTC
    assert parse_segment_start("other.mkv") is None


def test_index_list_and_delete(settings: Settings, database: Database) -> None:
    camera = CameraService(database).create_camera("Gate", "rtsp://h/x")
    service = RecordingService(database, settings.recording_path)
    path = _segment(settings.recording_path / "Gate", "Gate_2026-07-10_14-15-00.mkv")
    service.index_file(camera.id, path)
    service.index_file(camera.id, path, duration=900)  # final pass adds the duration
    (recording,) = service.list_recordings()
    assert recording.duration == 900 and recording.size == 1000
    assert recording.end_time == datetime(2026, 7, 10, 14, 30).astimezone(UTC).isoformat()
    day = datetime(2026, 7, 10).astimezone(UTC)
    assert service.list_recordings(start=day, end=day.replace(day=11)) == [recording]
    assert service.list_recordings(start=day.replace(day=12)) == []

    service.delete_recording(recording.id)
    assert not path.exists() and service.list_recordings() == []


def test_files_outside_storage_are_never_touched(
    settings: Settings, database: Database, tmp_path: Path
) -> None:
    camera = CameraService(database).create_camera("Gate", "rtsp://h/x")
    outside = tmp_path / "important.mkv"
    outside.write_bytes(b"x")
    database.execute(
        "INSERT INTO recordings (camera_id, filename, size) VALUES (?, ?, 1)",
        (camera.id, str(outside)),
    )
    service = RecordingService(database, settings.recording_path)
    (recording,) = service.list_recordings()
    assert service.file_path(recording) is None
    service.delete_recording(recording.id)
    assert outside.exists()


def test_reconcile_indexes_files_and_reads_durations(
    settings: Settings, database: Database
) -> None:
    cameras = CameraService(database)
    camera = cameras.create_camera("Gate", "rtsp://h/x")
    storage = StorageService(settings)
    _segment(storage.camera_directory(camera), "Gate_2026-07-10_14-00-00.mkv", age_days=1)
    recordings = RecordingService(database, settings.recording_path)
    reconcile = ReconcileService(settings, cameras, storage, recordings, probe=lambda _s, _p: 899.5)
    reconcile.run()
    (recording,) = recordings.list_recordings()
    assert recording.duration is None
    assert reconcile.probe_missing_durations() == 1
    assert recordings.list_recordings()[0].duration == 899.5


def test_relative_paths_are_migrated(
    settings: Settings, database: Database, tmp_path: Path
) -> None:
    camera = CameraService(database).create_camera("Gate", "rtsp://h/x")
    database.execute(
        "INSERT INTO recordings (camera_id, filename, size) VALUES (?, ?, 1)",
        (camera.id, "recordings/Gate/a.mkv"),
    )
    service = RecordingService(database, settings.recording_path)
    assert service.migrate_relative_paths(tmp_path) == 1
    assert service.list_recordings()[0].filename == str(
        (tmp_path / "recordings/Gate/a.mkv").resolve()
    )


def _cleanup(settings: Settings, database: Database, active=frozenset()) -> CleanupService:
    return CleanupService(
        settings,
        StorageService(settings),
        RecordingService(database, settings.recording_path),
        EventService(database),
        active_files=lambda: set(active),
    )


def test_retention_by_age_skips_active_file(settings: Settings, database: Database) -> None:
    directory = settings.recording_path / "Gate"
    old = _segment(directory, "Gate_2020-01-01_00-00-00.mkv", age_days=60)
    old_active = _segment(directory, "Gate_2020-01-01_00-15-00.mkv", age_days=60)
    recent = _segment(directory, "Gate_2026-07-10_14-15-00.mkv")
    result = _cleanup(settings, database, {old_active.resolve()}).run_once()
    assert result.deleted_files == 1
    assert not old.exists() and old_active.exists() and recent.exists()


def test_low_disk_deletes_oldest_until_target(
    settings: Settings, database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = settings.recording_path / "Gate"
    files = [
        _segment(directory, f"Gate_2026-07-10_14-{m:02d}-00.mkv", age_days=1 - m / 100)
        for m in range(5)
    ]
    minimum = 2500  # bytes; free space grows by 1000 for every deleted file

    def disk_stats(self: StorageService) -> DiskStats:
        free = sum(1000 for f in files if not f.exists())
        return DiskStats(10_000, 10_000 - free, free, free / 100, minimum, free < minimum)

    monkeypatch.setattr(StorageService, "disk_stats", disk_stats)
    cleanup = _cleanup(settings, database, {files[0].resolve()})
    result = CleanupResult()
    assert cleanup.recover_free_space(result) is True
    # oldest first, the file being written is skipped
    assert [f.exists() for f in files] == [True, False, False, False, True]
    assert result.deleted_for_space == 3
    assert any("Low disk space" in e.message for e in EventService(database).list_recent())


def test_low_disk_without_deletable_files_raises_one_error(
    settings: Settings, database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        StorageService, "disk_stats", lambda self: DiskStats(10, 10, 0, 0.0, 5, True)
    )
    cleanup = _cleanup(settings, database)
    assert cleanup.ensure_free_space() is False
    assert cleanup.ensure_free_space() is False
    errors = [e for e in EventService(database).list_recent() if e.level == "ERROR"]
    assert len(errors) == 1


def test_events_are_pruned(database: Database) -> None:
    events = EventService(database)
    for i in range(30):
        events.record("INFO", f"event {i}")
    database.execute("UPDATE events SET timestamp = '2000-01-01T00:00:00+00:00' WHERE id <= 5")
    assert events.prune(retention_days=30, max_events=20) == 10
    assert [e.message for e in events.list_recent(1)] == ["event 29"]


def test_recording_api(admin: TestClient, settings: Settings) -> None:
    camera = admin.post(
        "/api/cameras", json={"name": "Gate", "rtsp_url": "rtsp://h/x", "autostart": False}
    ).json()
    path = _segment(settings.recording_path / "Gate", "Gate_2026-07-10_14-15-00.mkv")
    admin.app.state.recording_service.index_file(camera["id"], path, 900)
    (recording,) = admin.get("/api/recordings", params={"camera_id": camera["id"]}).json()

    download = admin.get(f"/api/recordings/{recording['id']}/download")
    assert download.status_code == 200 and len(download.content) == 1000
    partial = admin.get(
        f"/api/recordings/{recording['id']}/stream", headers={"Range": "bytes=0-99"}
    )
    assert partial.status_code == 206 and len(partial.content) == 100

    assert admin.delete(f"/api/recordings/{recording['id']}").status_code == 204
    assert not path.exists()
    assert admin.get(f"/api/recordings/{recording['id']}/download").status_code == 404


def test_delete_camera_with_recordings(admin: TestClient, settings: Settings) -> None:
    camera = admin.post(
        "/api/cameras", json={"name": "Gate", "rtsp_url": "rtsp://h/x", "autostart": False}
    ).json()
    path = _segment(settings.recording_path / "Gate", "Gate_2026-07-10_14-15-00.mkv")
    admin.app.state.recording_service.index_file(camera["id"], path)
    response = admin.delete(f"/api/cameras/{camera['id']}", params={"delete_recordings": True})
    assert response.status_code == 204
    assert not path.exists()


def test_cleanup_endpoint(admin: TestClient) -> None:
    result = admin.post("/api/cleanup", headers=CSRF).json()
    assert result["deleted_files"] == 0 and result["errors"] == []


def test_delete_camera_keeps_camera_when_files_cannot_be_deleted(
    admin: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    camera = admin.post(
        "/api/cameras", json={"name": "Gate", "rtsp_url": "rtsp://h/x", "autostart": False}
    ).json()
    service = admin.app.state.recording_service
    paths = [
        _segment(settings.recording_path / "Gate", f"Gate_2026-07-10_14-{m:02d}-00Z.mkv")
        for m in range(3)
    ]
    for path in paths:
        service.index_file(camera["id"], path)
    locked = service.list_recordings()[0].id
    real_delete = service.delete_recording

    def delete(recording_id: int):
        if recording_id == locked:
            raise PermissionError("file in use")
        return real_delete(recording_id)

    monkeypatch.setattr(service, "delete_recording", delete)
    response = admin.delete(f"/api/cameras/{camera['id']}", params={"delete_recordings": True})
    assert response.status_code == 409
    assert admin.get(f"/api/cameras/{camera['id']}").status_code == 200
    assert [r.id for r in service.list_recordings()] == [locked]  # only the locked one is left
