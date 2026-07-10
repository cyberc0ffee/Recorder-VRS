from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.models.domain import Camera
from app.utils.paths import slugify_filename


def build_segment_pattern(camera: Camera, output_dir: Path) -> Path:
    safe_name = slugify_filename(camera.name)
    return output_dir / f"{safe_name}_%Y-%m-%d_%H-%M-%S.mkv"


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
        "-reset_timestamps",
        "1",
        "-strftime",
        "1",
        "-segment_format",
        "matroska",
        str(output_pattern),
    ]


def latest_segment(output_dir: Path) -> Path | None:
    files = [path for path in output_dir.glob("*.mkv") if path.is_file()]
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)

