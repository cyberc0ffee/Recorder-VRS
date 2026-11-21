from pathlib import Path

from app.core.database import Database
from app.services.camera_service import CameraService


def test_camera_crud(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.sqlite3")
    database.init_schema()
    service = CameraService(database)

    camera = service.create_camera("Entrance", "rtsp://example.test/stream")

    assert camera.id > 0
    assert camera.enabled is True
    assert service.get_camera(camera.id) == camera

    updated = service.update_camera(camera.id, name="Main Entrance", enabled=False)

    assert updated is not None
    assert updated.name == "Main Entrance"
    assert updated.enabled is False
    assert service.delete_camera(camera.id) is True
    assert service.get_camera(camera.id) is None
