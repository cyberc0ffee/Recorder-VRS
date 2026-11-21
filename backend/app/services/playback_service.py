from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from app.core.config import Settings
from app.workers.ffmpeg import build_playback_command

CHUNK_SIZE = 64 * 1024


class PlaybackBusyError(RuntimeError):
    pass


class Mp4Stream:
    """Iterator over the remuxed MP4. close() kills ffmpeg and frees the playback slot.

    A plain generator would skip its finally block if it is discarded before the first
    chunk (client gone before the response starts), leaking the slot and the process; here
    close() runs at the end of the stream, from the response's background task and, as a
    last resort, when the object is garbage collected.
    """

    def __init__(self, process: subprocess.Popen[bytes], release: threading.Semaphore) -> None:
        self._process = process
        self._release = release
        self._closed = False
        self._close_lock = threading.Lock()

    def __iter__(self) -> Mp4Stream:
        return self

    def __next__(self) -> bytes:
        stdout = self._process.stdout
        chunk = stdout.read(CHUNK_SIZE) if stdout is not None and not self._closed else b""
        if not chunk:
            self.close()
            raise StopIteration
        return chunk

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        try:
            if self._process.poll() is None:
                self._process.kill()
            self._process.wait()
            if self._process.stdout is not None:
                self._process.stdout.close()
        finally:
            self._release.release()

    def __del__(self) -> None:
        self.close()


class PlaybackService:
    """Browser playback: MKV segments are remuxed to fragmented MP4 while they stream.

    The number of concurrent remuxes is limited, so playback cannot starve recording.
    """

    def __init__(self, settings: Settings, max_concurrent: int = 4) -> None:
        self.settings = settings
        self._slots = threading.BoundedSemaphore(max_concurrent)

    def stream_mp4(self, source: Path) -> Mp4Stream:
        if not self._slots.acquire(blocking=False):
            raise PlaybackBusyError("Too many recordings are being played at the same time")
        try:
            process = subprocess.Popen(
                build_playback_command(self.settings, source),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            self._slots.release()
            raise
        return Mp4Stream(process, self._slots)
