"""Password hashing, session tokens and redaction of RTSP credentials (standard library only)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from urllib.parse import urlsplit, urlunsplit

MASK = "***"
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1
# user:password@ inside any URL (rtsp://, rtsps://, http://, tcp://...). The password runs to
# the LAST @ before the path, as for urlsplit and ffmpeg: "p@ss" is masked entirely.
_URL_CREDENTIALS_RE = re.compile(
    r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)(?P<user>[^:/@\s]*):[^\s/]*@"
)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32
    )
    encoded = [base64.b64encode(x).decode("ascii") for x in (salt, digest)]
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${encoded[0]}${encoded[1]}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if algorithm != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    """Only the SHA-256 of a session token is stored: a leaked database gives no valid session."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def mask_rtsp_url(url: str) -> str:
    """rtsp://user:secret@host/path -> rtsp://user:***@host/path (no password: unchanged)."""
    parts = urlsplit(url)
    if parts.password is None:
        return url
    host = parts.netloc.rsplit("@", 1)[1]
    return urlunsplit(parts._replace(netloc=f"{parts.username or ''}:{MASK}@{host}"))


def keep_stored_password(new_url: str, stored_url: str) -> str:
    """If the client sends back a masked URL (password "***"), reuse the stored password."""
    new_parts = urlsplit(new_url)
    if new_parts.password != MASK:
        return new_url
    stored_parts = urlsplit(stored_url)
    if stored_parts.password is None:
        raise ValueError("The RTSP URL contains a masked password but no password is stored")
    host = new_parts.netloc.rsplit("@", 1)[1]
    netloc = f"{new_parts.username or ''}:{stored_parts.password}@{host}"
    return urlunsplit(new_parts._replace(netloc=netloc))


def redact(text: str) -> str:
    """Removes passwords from any URL inside a free text (ffmpeg output, error messages)."""
    return _URL_CREDENTIALS_RE.sub(lambda m: f"{m['scheme']}{m['user']}:{MASK}@", text)
