from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from sqlite3 import Row

from app.core.database import Database
from app.core.security import keep_stored_password
from app.models.domain import Camera
from app.utils.paths import slugify_filename


def _row_to_camera(row: Row) -> Camera:
    return Camera(
        id=int(row["id"]),
        name=str(row["name"]),
        rtsp_url=str(row["rtsp_url"]),
        enabled=bool(row["enabled"]),
        autostart=bool(row["autostart"]),
        created_at=str(row["created_at"]),
    )


class CameraService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_cameras(self) -> list[Camera]:
        rows = self.database.fetch_all("SELECT * FROM cameras ORDER BY name COLLATE NOCASE")
        return [_row_to_camera(row) for row in rows]

    def get_camera(self, camera_id: int) -> Camera | None:
        row = self.database.fetch_one("SELECT * FROM cameras WHERE id = ?", (camera_id,))
        return _row_to_camera(row) if row is not None else None

    def _check_directory_name(self, name: str, camera_id: int | None = None) -> None:
        """Two cameras must never share a recording directory ("Front Door" vs "Front_Door")."""
        slug = slugify_filename(name).lower()
        for other in self.list_cameras():
            if other.id != camera_id and slugify_filename(other.name).lower() == slug:
                raise ValueError(f"Camera name too similar to existing camera: {other.name}")

    def create_camera(
        self,
        name: str,
        rtsp_url: str,
        enabled: bool = True,
        autostart: bool = True,
    ) -> Camera:
        name = name.strip()
        self._check_directory_name(name)
        created_at = datetime.now(UTC).isoformat()
        try:
            camera_id = self.database.execute(
                """
                INSERT INTO cameras (name, rtsp_url, enabled, autostart, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, rtsp_url.strip(), int(enabled), int(autostart), created_at),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"Camera name already exists: {name}") from exc

        camera = self.get_camera(camera_id)
        if camera is None:
            raise RuntimeError("Failed to read created camera")
        return camera

    def update_camera(
        self,
        camera_id: int,
        name: str | None = None,
        rtsp_url: str | None = None,
        enabled: bool | None = None,
        autostart: bool | None = None,
    ) -> Camera | None:
        existing = self.get_camera(camera_id)
        if existing is None:
            return None

        next_name = existing.name if name is None else name.strip()
        next_url = existing.rtsp_url
        if rtsp_url is not None:
            # the API only ever shows masked URLs: a masked password means "unchanged"
            next_url = keep_stored_password(rtsp_url.strip(), existing.rtsp_url)
        next_enabled = existing.enabled if enabled is None else enabled
        next_autostart = existing.autostart if autostart is None else autostart
        self._check_directory_name(next_name, camera_id)

        try:
            self.database.execute(
                """
                UPDATE cameras
                SET name = ?, rtsp_url = ?, enabled = ?, autostart = ?
                WHERE id = ?
                """,
                (next_name, next_url, int(next_enabled), int(next_autostart), camera_id),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"Camera name already exists: {next_name}") from exc

        return self.get_camera(camera_id)

    def delete_camera(self, camera_id: int) -> bool:
        return self.database.execute_rowcount("DELETE FROM cameras WHERE id = ?", (camera_id,)) > 0

    def list_autostart_cameras(self) -> list[Camera]:
        rows = self.database.fetch_all("""
            SELECT * FROM cameras
            WHERE enabled = 1 AND autostart = 1
            ORDER BY name COLLATE NOCASE
            """)
        return [_row_to_camera(row) for row in rows]
