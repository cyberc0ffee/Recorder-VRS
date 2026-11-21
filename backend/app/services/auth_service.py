from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import Settings
from app.core.database import Database
from app.core.security import hash_password, new_session_token, token_digest, verify_password

ADMIN_PASSWORD_ENV = "RTSP_RECORDER_ADMIN_PASSWORD"
INITIAL_PASSWORD_FILE = "initial_admin_password.txt"
MIN_PASSWORD_LENGTH = 10
logger = logging.getLogger("rtsp_recorder.auth")


@dataclass(frozen=True)
class User:
    id: int
    username: str
    role: str


class LoginThrottle:
    """Blocks a client address after too many failed logins in a time window."""

    def __init__(self, max_failures: int = 5, window_seconds: float = 900.0) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _recent(self, client: str, now: float) -> deque[float]:
        attempts = self._failures[client]
        while attempts and now - attempts[0] > self.window_seconds:
            attempts.popleft()
        return attempts

    def retry_after(self, client: str) -> int:
        """Seconds to wait before the next attempt (0 = allowed)."""
        now = time.monotonic()
        with self._lock:
            attempts = self._recent(client, now)
            if len(attempts) < self.max_failures:
                return 0
            return max(1, int(self.window_seconds - (now - attempts[0])))

    def failure(self, client: str) -> None:
        with self._lock:
            self._recent(client, time.monotonic()).append(time.monotonic())

    def success(self, client: str) -> None:
        with self._lock:
            self._failures.pop(client, None)


class AuthService:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings
        self.throttle = LoginThrottle()
        # a valid-looking hash, so unknown usernames take as long as wrong passwords
        self._dummy_hash = hash_password(secrets.token_urlsafe(16))

    # --- users ---------------------------------------------------------------------------

    def ensure_admin(self) -> Path | None:
        """Creates the first administrator if there are no users.

        The password comes from RTSP_RECORDER_ADMIN_PASSWORD; otherwise a random one is
        written (owner-only permissions) next to the database and its path is returned.
        """
        if self.database.fetch_one("SELECT id FROM users LIMIT 1") is not None:
            return None
        password = os.getenv(ADMIN_PASSWORD_ENV)
        password_file: Path | None = None
        if not password:
            password = secrets.token_urlsafe(12)
            password_file = self.settings.database_path.parent / INITIAL_PASSWORD_FILE
            password_file.write_text(
                f"username: {self.settings.admin_username}\npassword: {password}\n",
                encoding="utf-8",
            )
            password_file.chmod(0o600)
        self.create_user(self.settings.admin_username, password, role="admin", check_length=False)
        logger.warning(
            "Created administrator %r; initial password %s",
            self.settings.admin_username,
            f"written to {password_file}" if password_file else f"taken from {ADMIN_PASSWORD_ENV}",
        )
        return password_file

    def create_user(
        self, username: str, password: str, role: str = "admin", check_length: bool = True
    ) -> User:
        if check_length:
            self._check_password(password)
        now = datetime.now(UTC).isoformat()
        user_id = self.database.execute(
            "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
            (username, hash_password(password), role, now),
        )
        return User(id=user_id, username=username, role=role)

    def set_password(self, username: str, password: str) -> None:
        """Sets a new password and closes every open session of that user."""
        self._check_password(password)
        row = self.database.fetch_one("SELECT id FROM users WHERE username = ?", (username,))
        if row is None:
            self.create_user(username, password)
            return
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (hash_password(password), row["id"]),
            )
            connection.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
        initial = self.settings.database_path.parent / INITIAL_PASSWORD_FILE
        initial.unlink(missing_ok=True)

    def change_password(self, user: User, current: str, new: str) -> bool:
        row = self.database.fetch_one("SELECT password_hash FROM users WHERE id = ?", (user.id,))
        if row is None or not verify_password(current, row["password_hash"]):
            return False
        self.set_password(user.username, new)
        return True

    @staticmethod
    def _check_password(password: str) -> None:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"The password must be at least {MIN_PASSWORD_LENGTH} characters long")

    # --- sessions ------------------------------------------------------------------------

    def authenticate(self, username: str, password: str) -> User | None:
        row = self.database.fetch_one(
            "SELECT id, username, role, password_hash FROM users WHERE username = ?", (username,)
        )
        if row is None:
            verify_password(password, self._dummy_hash)
            return None
        if not verify_password(password, row["password_hash"]):
            return None
        return User(id=int(row["id"]), username=str(row["username"]), role=str(row["role"]))

    def create_session(self, user: User) -> str:
        token = new_session_token()
        now = datetime.now(UTC)
        expires = now + timedelta(hours=self.settings.session_hours)
        self.database.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at)"
            " VALUES (?, ?, ?, ?)",
            (token_digest(token), user.id, now.isoformat(), expires.isoformat()),
        )
        return token

    def user_for_token(self, token: str | None) -> User | None:
        if not token:
            return None
        row = self.database.fetch_one(
            """
            SELECT users.id, users.username, users.role, sessions.expires_at
            FROM sessions JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = ?
            """,
            (token_digest(token),),
        )
        if row is None:
            return None
        if datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC):
            self.end_session(token)
            return None
        return User(id=int(row["id"]), username=str(row["username"]), role=str(row["role"]))

    def end_session(self, token: str | None) -> None:
        if token:
            self.database.execute(
                "DELETE FROM sessions WHERE token_hash = ?", (token_digest(token),)
            )

    def purge_expired_sessions(self) -> int:
        return self.database.execute_rowcount(
            "DELETE FROM sessions WHERE expires_at <= ?", (datetime.now(UTC).isoformat(),)
        )
