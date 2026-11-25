"""TEMPORARY diagnostic: how the segment file grows with audio. Removed after the fix."""

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

RTSP_TEST_URL = os.getenv("RTSP_TEST_URL")
pytestmark = pytest.mark.skipif(not RTSP_TEST_URL or not shutil.which("ffmpeg"), reason="diag")


def _publish(url: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "warning", "-re",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10",
            "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=8000",
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-g", "10",
            "-c:a", "pcm_mulaw",
            "-f", "rtsp", "-rtsp_transport", "tcp", url,
        ],
        stdin=subprocess.DEVNULL,
    )  # fmt: skip


def _run(url: str, out: Path, maps: list[str], extra: list[str]) -> str:
    out.mkdir(parents=True)
    cmd = [
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "verbose", "-rtsp_transport", "tcp",
        "-timeout", "3000000", "-i", url, *maps, "-c", "copy", *extra,
        "-f", "segment", "-segment_time", "20", "-segment_atclocktime", "1",
        "-reset_timestamps", "1", "-strftime", "1", "-segment_format", "matroska",
        str(out / "s_%Y-%m-%d_%H-%M-%SZ.mkv"),
    ]  # fmt: skip
    log = out / "ffmpeg.log"
    with log.open("w") as handle:
        p = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stderr=handle, env={**os.environ, "TZ": "UTC0"}
        )
        lines = []
        start = time.monotonic()
        while time.monotonic() - start < 9:
            time.sleep(0.5)
            sizes = {f.name[-13:-4]: f.stat().st_size for f in sorted(out.glob("*.mkv"))}
            lines.append(f"{time.monotonic() - start:4.1f} {sizes}")
        p.terminate()
        p.wait(10)
    tail = [
        line
        for line in log.read_text().splitlines()
        if "Stream" in line or "rror" in line or "arn" in line.lower()
    ][:25]
    return "\n".join([" ".join(maps + extra)] + lines + tail)


def test_diag(tmp_path: Path) -> None:
    url = RTSP_TEST_URL.rsplit("/", 1)[0] + "/diag"
    publisher = _publish(url)
    try:
        time.sleep(3)
        reports = [
            _run(url, tmp_path / "a", ["-map", "0:v"], []),
            _run(url, tmp_path / "b", ["-map", "0:v", "-map", "0:a?"], []),
            _run(
                url, tmp_path / "c", ["-map", "0:v", "-map", "0:a?"], ["-max_interleave_delta", "0"]
            ),
            _run(url, tmp_path / "d", ["-map", "0:v", "-map", "0:a?"], ["-flush_packets", "1"]),
        ]
    finally:
        publisher.kill()
    raise AssertionError("\n\n".join(reports))
