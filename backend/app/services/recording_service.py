from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from sqlite3 import Row

from app.core.database import Database
from app.models.domain import Recording


_TIMESTAMP_RE = re.compile(r"_(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})\.mkv$")


def _row_to_recording(row: Row) -> Recording:
    return Recording(
        id=int(row["id"]),
        camera_id=int(row["camera_id"]),
        filename=str(row["filename"]),
        duration=float(row["duration"]) if row["duration"] is not None else None,
        size=int(row["size"]),
        start_time=str(row["start_time"]) if row["start_time"] is not None else None,
        end_time=str(row["end_time"]) if row["end_time"] is not None else None,
    )


def _parse_timestamp(filename: str) -> str | None:
    match = _TIMESTAMP_RE.search(filename)
    if match is None:
        return None
    raw_value = f"{match.group(1)} {match.group(2).replace('-', ':')}"
    try:
        parsed = datetime.strptime(raw_value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc).isoformat()


class RecordingService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def index_file(self, camera_id: int, file_path: Path) -> None:
        if not file_path.exists() or not file_path.is_file():
            return

        size = file_path.stat().st_size
        start_time = _parse_timestamp(file_path.name)
        end_time = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc).isoformat()
        self.database.execute(
            """
            INSERT INTO recordings (camera_id, filename, duration, size, start_time, end_time)
            VALUES (?, ?, NULL, ?, ?, ?)
            ON CONFLICT(filename) DO UPDATE SET
                size = excluded.size,
                end_time = excluded.end_time
            """,
            (camera_id, str(file_path), size, start_time, end_time),
        )

    def list_by_camera(self, camera_id: int, limit: int = 200) -> list[Recording]:
        rows = self.database.fetch_all(
            """
            SELECT * FROM recordings
            WHERE camera_id = ?
            ORDER BY start_time DESC, id DESC
            LIMIT ?
            """,
            (camera_id, max(1, min(limit, 1000))),
        )
        return [_row_to_recording(row) for row in rows]

    def list_recordings(self, camera_id: int | None = None, limit: int = 500) -> list[Recording]:
        if camera_id is None:
            rows = self.database.fetch_all(
                """
                SELECT * FROM recordings
                ORDER BY start_time DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(limit, 1000)),),
            )
        else:
            rows = self.database.fetch_all(
                """
                SELECT * FROM recordings
                WHERE camera_id = ?
                ORDER BY start_time DESC, id DESC
                LIMIT ?
                """,
                (camera_id, max(1, min(limit, 1000))),
            )
        return [_row_to_recording(row) for row in rows]

    def get_recording(self, recording_id: int) -> Recording | None:
        row = self.database.fetch_one("SELECT * FROM recordings WHERE id = ?", (recording_id,))
        return _row_to_recording(row) if row is not None else None

    def delete_by_filename(self, filename: str) -> None:
        self.database.execute("DELETE FROM recordings WHERE filename = ?", (filename,))

    def delete_recording(self, recording_id: int) -> Recording | None:
        recording = self.get_recording(recording_id)
        if recording is None:
            return None
        file_path = Path(recording.filename)
        if file_path.exists():
            file_path.unlink()
        self.database.execute("DELETE FROM recordings WHERE id = ?", (recording_id,))
        return recording

    def prune_missing_files(self) -> int:
        rows = self.database.fetch_all("SELECT filename FROM recordings")
        deleted = 0
        for row in rows:
            filename = str(row["filename"])
            if not Path(filename).exists():
                self.delete_by_filename(filename)
                deleted += 1
        return deleted
