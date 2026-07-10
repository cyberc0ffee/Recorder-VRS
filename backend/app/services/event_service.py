from __future__ import annotations

import logging
from datetime import datetime, timezone
from sqlite3 import Row

from app.core.database import Database
from app.models.domain import Event


def _row_to_event(row: Row) -> Event:
    return Event(
        id=int(row["id"]),
        timestamp=str(row["timestamp"]),
        level=str(row["level"]),
        message=str(row["message"]),
        camera_id=int(row["camera_id"]) if row["camera_id"] is not None else None,
    )


class EventService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.logger = logging.getLogger("rtsp_recorder.events")

    def record(self, level: str, message: str, camera_id: int | None = None) -> Event:
        normalized_level = level.upper()
        timestamp = datetime.now(timezone.utc).isoformat()
        event_id = self.database.execute(
            """
            INSERT INTO events (timestamp, level, message, camera_id)
            VALUES (?, ?, ?, ?)
            """,
            (timestamp, normalized_level, message, camera_id),
        )
        self.logger.log(
            getattr(logging, normalized_level, logging.INFO),
            message,
            extra={"extra_fields": {"camera_id": camera_id}},
        )
        row = self.database.fetch_one("SELECT * FROM events WHERE id = ?", (event_id,))
        if row is None:
            raise RuntimeError("Failed to read created event")
        return _row_to_event(row)

    def list_recent(self, limit: int = 100) -> list[Event]:
        rows = self.database.fetch_all(
            "SELECT * FROM events ORDER BY timestamp DESC, id DESC LIMIT ?",
            (max(1, min(limit, 500)),),
        )
        return [_row_to_event(row) for row in rows]

