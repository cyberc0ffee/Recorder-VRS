from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from sqlite3 import Row

from app.core.database import Database
from app.core.security import redact
from app.models.domain import Event

LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


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
        normalized_level = level.upper() if level.upper() in LEVELS else "INFO"
        message = redact(message)
        timestamp = datetime.now(UTC).isoformat()
        event_id = self.database.execute(
            "INSERT INTO events (timestamp, level, message, camera_id) VALUES (?, ?, ?, ?)",
            (timestamp, normalized_level, message, camera_id),
        )
        self.logger.log(
            getattr(logging, normalized_level),
            message,
            extra={"extra_fields": {"camera_id": camera_id}},
        )
        return Event(event_id, timestamp, normalized_level, message, camera_id)

    def list_recent(self, limit: int = 100, camera_id: int | None = None) -> list[Event]:
        limit = max(1, min(limit, 500))
        if camera_id is None:
            rows = self.database.fetch_all(
                "SELECT * FROM events ORDER BY timestamp DESC, id DESC LIMIT ?", (limit,)
            )
        else:
            rows = self.database.fetch_all(
                "SELECT * FROM events WHERE camera_id = ? ORDER BY timestamp DESC, id DESC LIMIT ?",
                (camera_id, limit),
            )
        return [_row_to_event(row) for row in rows]

    def prune(self, retention_days: int, max_events: int) -> int:
        """Deletes events older than the retention and keeps at most max_events rows."""
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
        deleted = self.database.execute_rowcount(
            "DELETE FROM events WHERE timestamp < ?", (cutoff,)
        )
        deleted += self.database.execute_rowcount(
            """
            DELETE FROM events WHERE id NOT IN (
                SELECT id FROM events ORDER BY timestamp DESC, id DESC LIMIT ?
            )
            """,
            (max_events,),
        )
        return deleted
