"""Stand-in for ffmpeg used by the worker tests.

    fake_ffmpeg.py MODE OUTPUT_PATTERN [SEGMENT_SECONDS]

record  writes growing segments named with strftime(OUTPUT_PATTERN), one per SEGMENT_SECONDS
stall   writes one chunk, then hangs without writing (the watchdog must restart it)
fail    prints an error containing credentials and exits with code 1
"""

import signal
import sys
import time
from datetime import UTC, datetime

mode, pattern = sys.argv[1], sys.argv[2]
segment_seconds = float(sys.argv[3]) if len(sys.argv) > 3 else 1.1

if mode == "fail":
    sys.stderr.write("rtsp://admin:s3cret@10.0.0.9:554/live: Connection refused\n")
    sys.stderr.flush()
    sys.exit(1)

running = True


def _stop(*_):
    global running
    running = False


signal.signal(signal.SIGTERM, _stop)

if mode == "stall":
    with open(datetime.now(UTC).strftime(pattern), "ab") as f:
        f.write(b"\0" * 1000)
    while running:
        time.sleep(0.05)
    sys.exit(0)

while running:
    started = time.monotonic()
    with open(datetime.now(UTC).strftime(pattern), "ab") as f:
        while running and time.monotonic() - started < segment_seconds:
            f.write(b"\0" * 1000)
            f.flush()
            time.sleep(0.05)
    time.sleep(0.01)
