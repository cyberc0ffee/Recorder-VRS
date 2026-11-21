"""ffmpeg / ffprobe command lines. Video is never transcoded."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app.core.config import Settings
from app.models.domain import Camera
from app.utils.paths import slugify_filename

PROBE_TIMEOUT_SECONDS = 20


def build_segment_pattern(camera: Camera, output_dir: Path) -> Path:
    safe_name = slugify_filename(camera.name)
    # UTC names: no duplicate names when the clock goes back at the end of daylight saving
    return output_dir / f"{safe_name}_%Y-%m-%d_%H-%M-%SZ.mkv"


def recorder_environment() -> dict[str, str]:
    """ffmpeg's -strftime uses local time: run it in UTC ("UTC0" is valid POSIX and CRT)."""
    return {**os.environ, "TZ": "UTC0"}


def build_ffmpeg_command(settings: Settings, camera: Camera, output_dir: Path) -> list[str]:
    output_pattern = build_segment_pattern(camera, output_dir)
    return [
        settings.ffmpeg_binary,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "warning",
        "-rtsp_transport",
        "tcp",
        # socket I/O timeout (microseconds, ffmpeg >= 5): a dead stream ends ffmpeg instead
        # of leaving it waiting until the watchdog notices
        "-timeout",
        str(settings.rtsp_timeout_seconds * 1_000_000),
        "-i",
        camera.rtsp_url,
        "-map",
        "0",
        "-c",
        "copy",
        "-f",
        "segment",
        "-segment_time",
        str(settings.segment_duration_seconds),
        # segments start at round clock times (14:00, 14:15...), easier to browse
        "-segment_atclocktime",
        "1",
        "-reset_timestamps",
        "1",
        "-strftime",
        "1",
        "-segment_format",
        "matroska",
        str(output_pattern),
    ]


def build_playback_command(settings: Settings, source: Path) -> list[str]:
    """Remuxes an MKV segment to fragmented MP4 on stdout, playable by browsers.

    Video is copied; audio (often G.711 from cameras, not allowed in MP4) becomes AAC.
    """
    return [
        settings.ffmpeg_binary,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-f",
        "mp4",
        "-movflags",
        "frag_keyframe+empty_moov+default_base_moof",
        "pipe:1",
    ]


def probe_duration(settings: Settings, path: Path) -> float | None:
    """Duration in seconds read by ffprobe, or None if it cannot be read."""
    command = [
        settings.ffprobe_binary,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=PROBE_TIMEOUT_SECONDS, check=False
        )
        return round(float(result.stdout.strip()), 3) if result.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def latest_segment(output_dir: Path, since: float = 0.0) -> Path | None:
    """Newest segment modified at or after `since` (epoch seconds).

    Segment names embed their start time, so the greatest name is the newest file.
    """
    newest: Path | None = None
    for path in output_dir.glob("*.mkv"):
        try:
            if path.stat().st_mtime < since:
                continue
        except OSError:
            continue
        if newest is None or path.name > newest.name:
            newest = path
    return newest
