from pathlib import Path

from app.core.config import Settings
from app.models.domain import Camera
from app.workers.ffmpeg import build_ffmpeg_command, build_segment_pattern


def test_ffmpeg_command_uses_copy_tcp_segmented_mkv(tmp_path: Path) -> None:
    settings = Settings(segment_duration_seconds=900)
    camera = Camera(
        id=1,
        name="Entrance",
        rtsp_url="rtsp://example.test/stream",
        enabled=True,
        autostart=True,
        created_at="2026-07-10T00:00:00+00:00",
    )

    command = build_ffmpeg_command(settings, camera, tmp_path)

    assert "-rtsp_transport" in command
    assert "tcp" in command
    assert "-c" in command
    assert "copy" in command
    assert "-f" in command
    assert "segment" in command
    assert "-segment_format" in command
    assert "matroska" in command
    assert "Entrance_%Y-%m-%d_%H-%M-%S.mkv" in command[-1]


def test_segment_pattern_sanitizes_camera_name(tmp_path: Path) -> None:
    camera = Camera(
        id=1,
        name="Front Door / East",
        rtsp_url="rtsp://example.test/stream",
        enabled=True,
        autostart=True,
        created_at="2026-07-10T00:00:00+00:00",
    )

    pattern = build_segment_pattern(camera, tmp_path)

    assert pattern.name == "Front_Door_East_%Y-%m-%d_%H-%M-%S.mkv"

