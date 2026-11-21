from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from sqlite3 import Row

from app.core.database import Database
from app.models.domain import Recording

_TIMESTAMP_RE = re.compile(r"_(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})(Z?)\.mkv$")


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


def parse_segment_start(filename: str) -> datetime | None:
    """Start time encoded in the segment name.

    Current names end with "Z" (UTC). Names written by 0.1 have no suffix and carry the
    server's local time.
    """
    match = _TIMESTAMP_RE.search(filename)
    if match is None:
        return None
    try:
        naive = datetime.strptime(f"{match[1]} {match[2]}", "%Y-%m-%d %H-%M-%S")
    except ValueError:
        return None
    if match[3]:
        return naive.replace(tzinfo=UTC)
    return naive.astimezone(UTC)


class RecordingService:
    def __init__(self, database: Database, recording_root: Path) -> None:
        self.database = database
        self.recording_root = recording_root.resolve()

    def index_file(self, camera_id: int, file_path: Path, duration: float | None = None) -> None:
        """Inserts or updates one segment: size, end time and, when known, duration."""
        try:
            stat = file_path.stat()
        except OSError:
            return
        start = parse_segment_start(file_path.name)
        if start is not None and duration is not None:
            end = start + timedelta(seconds=duration)
        else:
            end = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
        self.database.execute(
            """
            INSERT INTO recordings (camera_id, filename, duration, size, start_time, end_time)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(filename) DO UPDATE SET
                size = excluded.size,
                end_time = excluded.end_time,
                duration = COALESCE(excluded.duration, recordings.duration)
            """,
            (
                camera_id,
                str(file_path.resolve()),
                duration,
                stat.st_size,
                start.isoformat() if start else None,
                end.isoformat(),
            ),
        )

    def known_filenames(self) -> set[str]:
        rows = self.database.fetch_all("SELECT filename FROM recordings")
        return {str(row["filename"]) for row in rows}

    def without_duration(self) -> list[Recording]:
        rows = self.database.fetch_all("SELECT * FROM recordings WHERE duration IS NULL")
        return [_row_to_recording(row) for row in rows]

    def list_recordings(
        self,
        camera_id: int | None = None,
        limit: int = 500,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Recording]:
        clauses: list[str] = []
        params: list[object] = []
        if camera_id is not None:
            clauses.append("camera_id = ?")
            params.append(camera_id)
        if start is not None:
            clauses.append("COALESCE(end_time, start_time) >= ?")
            params.append(start.astimezone(UTC).isoformat())
        if end is not None:
            clauses.append("start_time < ?")
            params.append(end.astimezone(UTC).isoformat())
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(max(1, min(limit, 5000)))
        rows = self.database.fetch_all(
            f"SELECT * FROM recordings {where} ORDER BY start_time DESC, id DESC LIMIT ?",
            tuple(params),
        )
        return [_row_to_recording(row) for row in rows]

    def list_by_camera(self, camera_id: int, limit: int = 200) -> list[Recording]:
        return self.list_recordings(camera_id=camera_id, limit=limit)

    def get_recording(self, recording_id: int) -> Recording | None:
        row = self.database.fetch_one("SELECT * FROM recordings WHERE id = ?", (recording_id,))
        return _row_to_recording(row) if row is not None else None

    def file_path(self, recording: Recording) -> Path | None:
        """Path of the recording, only if it lies inside the recording root."""
        path = Path(recording.filename).resolve()
        if not path.is_relative_to(self.recording_root):
            return None
        return path

    def delete_by_filename(self, filename: str) -> None:
        self.database.execute("DELETE FROM recordings WHERE filename = ?", (filename,))

    def delete_recording(self, recording_id: int) -> Recording | None:
        recording = self.get_recording(recording_id)
        if recording is None:
            return None
        path = self.file_path(recording)
        if path is not None:
            path.unlink(missing_ok=True)
        self.database.execute("DELETE FROM recordings WHERE id = ?", (recording_id,))
        return recording

    def delete_camera_recordings(self, camera_id: int) -> tuple[int, int]:
        """Deletes every recording of a camera; returns (deleted, files that could not be removed).

        Rows whose file cannot be removed are kept, so the files stay visible and deletable.
        """
        deleted = failed = 0
        rows = self.database.fetch_all(
            "SELECT id FROM recordings WHERE camera_id = ?", (camera_id,)
        )
        for row in rows:
            try:
                if self.delete_recording(int(row["id"])) is not None:
                    deleted += 1
            except OSError:
                failed += 1
        return deleted, failed

    def prune_missing_files(self) -> int:
        deleted = 0
        for filename in self.known_filenames():
            if not Path(filename).exists():
                self.delete_by_filename(filename)
                deleted += 1
        return deleted

    def migrate_relative_paths(self, base: Path) -> int:
        """Older versions stored paths relative to the working directory: make them absolute."""
        changed = 0
        for row in self.database.fetch_all("SELECT id, filename FROM recordings"):
            path = Path(row["filename"])
            if path.is_absolute():
                continue
            absolute = str((base / path).resolve())
            if self.database.fetch_one("SELECT id FROM recordings WHERE filename = ?", (absolute,)):
                self.database.execute("DELETE FROM recordings WHERE id = ?", (row["id"],))
            else:
                self.database.execute(
                    "UPDATE recordings SET filename = ? WHERE id = ?", (absolute, row["id"])
                )
            changed += 1
        return changed
