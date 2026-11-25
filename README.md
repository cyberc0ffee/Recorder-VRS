# RTSP Recorder

Lightweight Python/Vue Network Video Recorder for continuous RTSP recording without transcoding.

## Features

* FastAPI backend with automatic OpenAPI documentation, SQLite database
* Login for the dashboard and the API (scrypt password hashes, HttpOnly session cookie, CSRF
  protection, throttling of failed logins)
* Camera passwords never leave the server: the API and the logs show `rtsp://user:***@host`
* Dedicated ffmpeg worker per camera with a watchdog: restart on exit or when the file stops
  growing, exponential back-off, one event per outage instead of one per retry; a supervisor
  restarts any camera that should be recording and is not (see [Reliability](#reliability))
* MKV segments with codec copy, aligned to the clock (14:00, 14:15, …)
* Retention by age **and** by free space: below the minimum the oldest recordings are deleted
  first; files being written are never touched
* Duration and final size of every segment (ffprobe); recordings on disk are re-indexed at startup
* Browser playback: segments are remuxed to MP4 on the fly (video copied, never transcoded)
* Vue dashboard: system metrics, camera states, events, recordings filtered by camera and day
* Docker (non-root, read-only, healthcheck) and systemd (hardened) deployment files

## Quick start with Docker

```bash
cp config.example.yaml config.yaml
mkdir -p data logs recordings
sudo chown -R 10001:10001 data logs recordings   # the container runs as uid 10001
RTSP_RECORDER_ADMIN_PASSWORD='choose-a-long-password' docker compose up -d --build
```

Open `http://<server>:8000` and sign in as `admin`. `TZ` in `docker-compose.yml` (default
`Europe/Rome`) sets the time zone of the logs; segment names are always in UTC.

If `RTSP_RECORDER_ADMIN_PASSWORD` is not set on the first start, a random password is written
to `data/initial_admin_password.txt` (readable only by its owner). Change it from the
**Account** page; the file is deleted when the password is changed.

## Security notes

* **Authentication.** Every `/api` endpoint except login and `/health` requires a session.
  State-changing requests also need the `X-Requested-With: rtsp-recorder` header (the
  dashboard sends it), so other web sites cannot trigger actions with your cookie.
* **HTTPS.** The application speaks plain HTTP. Outside a trusted LAN, put it behind a
  reverse proxy with TLS (Caddy, nginx, Traefik) and set `cookie_secure: true`. Login
  throttling is per client address: uvicorn takes it from `X-Forwarded-For` only when the
  proxy is trusted (`127.0.0.1` by default; for a proxy elsewhere, e.g. another container, set
  `FORWARDED_ALLOW_IPS` to its address). Otherwise all clients share the proxy address and
  failed logins of one of them delay the others.
* **Camera credentials.** They are stored in the SQLite database, which must stay readable only
  by the service user. ffmpeg needs the URL on its command line: the systemd unit uses
  `ProtectProc=invisible` so other users cannot read it; in Docker the process is isolated.
* **Reset a password** (e.g. forgotten admin password):

  ```bash
  docker compose exec rtsp-recorder python -m app.cli set-password    # Docker
  cd /opt/rtsp-recorder && sudo -u rtsp-recorder PYTHONPATH=backend \
      .venv/bin/python -m app.cli --config config.yaml set-password   # systemd
  ```

## Local development

Backend (Python 3.12, ffmpeg 5 or later on `PATH`):

```bash
python -m venv .venv
source .venv/bin/activate                         # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
export RTSP_RECORDER_ADMIN_PASSWORD='dev-password-123'
uvicorn app.main:app --reload --app-dir backend
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server proxies `/api` to `http://localhost:8000`. API documentation:
`http://localhost:8000/docs`.

## Configuration

Copy `config.example.yaml` to `config.yaml`; every key is documented there. The most
important ones:

```yaml
recording_path: /mnt/videos
retention_days: 30
minimum_free_disk_gb: 20       # below this, the oldest recordings are deleted
free_disk_margin_gb: 2         # ...until free space is back above minimum + margin
segment_duration_seconds: 900
restart_delay_seconds: 2       # first retry; doubles up to max_restart_delay_seconds (60)
cookie_secure: true            # when served over HTTPS
```

## Recording format

Each camera writes segmented MKV files into its own directory:

```text
recordings/Entrance/Entrance_2026-07-10_12-15-00Z.mkv
```

The name carries the start time in UTC (`Z`), so names never repeat when the clock goes back at
the end of daylight saving time; the dashboard shows times in the browser's time zone. ffmpeg uses TCP transport and
`-c copy`, so video is never transcoded. Browser playback remuxes the MKV to MP4 while it
streams; H.265 cameras play only in browsers that support HEVC (otherwise download the MKV).

## API

```text
POST   /api/auth/login | /api/auth/logout | /api/auth/password      GET /api/auth/me
GET    /api/cameras                 POST /api/cameras
GET    /api/cameras/{id}            PUT  /api/cameras/{id}
DELETE /api/cameras/{id}?delete_recordings=false
POST   /api/cameras/{id}/start      POST /api/cameras/{id}/stop
GET    /api/recordings?camera_id=&start=&end=&limit=
GET    /api/recordings/{id}/download | /stream (MKV) | /play (MP4)
DELETE /api/recordings/{id}
GET    /api/system                  GET  /api/events?limit=&camera_id=
POST   /api/cleanup                 GET  /health      GET /health/recording
```

Camera states: `stopped`, `starting`, `recording` (the segment file is growing),
`reconnecting` (waiting before the next attempt; see `next_retry_at` and `last_error`).

## Reliability

Recording is designed to keep going on its own, and to tell you when it cannot:

* **Camera or network down.** ffmpeg gives up after `rtsp_timeout_seconds` without data and is
  restarted after 2 s, then 4, 8… up to `max_restart_delay_seconds` (60 s): that is also the
  longest gap after the camera comes back. A stream that stays connected but stops sending
  video is restarted when the segment has not grown for `file_stale_seconds`.
* **Nothing around the recording can stop it.** Database errors (locked, disk full), a log
  that cannot be written and internal errors are logged, and ffmpeg keeps writing; at worst
  ffmpeg is restarted. Segment durations are read in the background, so a restart never waits
  for them.
* **Supervisor.** Every 30 s, each camera that should be recording and is not gets started
  again: a start refused because the disk was full, a restart that failed after editing the
  camera, or a worker that ended unexpectedly. Only an explicit Stop ends recording.
* **Every packet reaches the disk at once.** ffmpeg would otherwise buffer 256 KB, which a
  low-bitrate stream (H.265+ on a still scene, a substream) can take minutes to fill: the file
  would look stalled and a power cut would lose that video.
* **Only video and audio are recorded.** Data tracks (ONVIF metadata) would make the MKV header
  fail. If a camera's audio track causes errors, set `record_audio: false`.
* **The service itself** is restarted by systemd (`Restart=always`) or Docker
  (`restart: unless-stopped`); ffmpeg segments are MKV, readable even after a power failure.

**Monitoring.** `GET /health/recording` answers `200 {"status": "ok", "expected": 3,
"recording": 3}` when every camera that should record is recording, and **503** otherwise (no
login needed, it only returns these counters). Point an external monitor at it (Uptime Kuma,
Zabbix, Healthchecks…) to be alerted; allow a minute after a start or a camera restart.

## Tests and lint

```bash
pytest --cov=app                  # ffmpeg is simulated: no camera needed
ruff check backend
black --check backend
```

The end-to-end test with the real ffmpeg runs when an RTSP stream is available:

```bash
RTSP_TEST_URL=rtsp://127.0.0.1:8554/test pytest backend/tests/test_integration_ffmpeg.py
```

The CI (GitHub Actions) runs lint, all tests with a MediaMTX test stream, the frontend build
and the Docker build.

## Upgrading from 0.1

* On the first start an administrator is created (see above): the dashboard asks for a login.
* Existing recordings are re-indexed automatically; stored relative paths become absolute.
* New segment names are in UTC with a `Z` suffix; 0.1 names (local time, no suffix) are still
  read correctly.
* `cors_origins` is now empty by default: it is only needed when the frontend runs on another
  origin without the Vite proxy.
