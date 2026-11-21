from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS cameras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    rtsp_url TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    autostart INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id INTEGER NOT NULL,
    filename TEXT NOT NULL UNIQUE,
    duration REAL,
    size INTEGER NOT NULL DEFAULT 0,
    start_time TEXT,
    end_time TEXT,
    FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    camera_id INTEGER,
    FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'admin',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_recordings_camera_start ON recordings(camera_id, start_time);
CREATE INDEX IF NOT EXISTS idx_recordings_start ON recordings(start_time);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
"""


class Database:
    """Thread-safe SQLite access wrapper shared by services and workers."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = NORMAL")
        self._connection.execute("PRAGMA busy_timeout = 5000")

    def init_schema(self) -> None:
        with self.transaction() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._connection
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise

    def fetch_all(self, query: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._connection.execute(query, params).fetchall())

    def fetch_one(self, query: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._connection.execute(query, params).fetchone()

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> int:
        """Runs one statement in its own transaction and returns lastrowid."""
        with self.transaction() as connection:
            return int(connection.execute(query, params).lastrowid or 0)

    def execute_rowcount(self, query: str, params: tuple[Any, ...] = ()) -> int:
        """Runs one statement in its own transaction and returns the number of changed rows."""
        with self.transaction() as connection:
            return int(connection.execute(query, params).rowcount)

    def close(self) -> None:
        with self._lock:
            self._connection.close()
