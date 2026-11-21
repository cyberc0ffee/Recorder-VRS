from __future__ import annotations

import re
from pathlib import Path

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def slugify_filename(value: str) -> str:
    normalized = _SAFE_FILENAME_RE.sub("_", value.strip())
    normalized = normalized.strip("._")
    return normalized or "camera"


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
