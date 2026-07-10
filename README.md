# RTSP Recorder

Lightweight Python/Vue Network Video Recorder for continuous RTSP recording without transcoding.

## Features

* FastAPI backend with automatic OpenAPI documentation
* SQLite database for cameras, recordings and events
* Dedicated ffmpeg worker per camera
* Watchdog restart on process exit or stale output files
* MKV segmented recording with codec copy
* Disk monitoring and retention cleanup
* Vue dashboard for system metrics, camera status and events
* Recording browser with list, download, delete and HTML5 playback where supported
* Docker Compose and systemd deployment files

## Local Backend

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --app-dir backend
```

API documentation is available at:

```text
http://localhost:8000/docs
```

Core endpoints:

```text
GET /api/cameras
POST /api/cameras
POST /api/cameras/{id}/start
POST /api/cameras/{id}/stop
GET /api/recordings
GET /api/recordings/{id}/download
DELETE /api/recordings/{id}
GET /api/system
GET /api/events
POST /api/cleanup
```

## Local Frontend

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server proxies `/api` to `http://localhost:8000`.

## Docker

```bash
docker compose up --build
```

The application listens on:

```text
http://localhost:8000
```

## Configuration

Copy `config.example.yaml` to `config.yaml` and adjust paths:

```yaml
recording_path: /mnt/videos
retention_days: 30
minimum_free_disk_gb: 20
ffmpeg_binary: ffmpeg
restart_delay_seconds: 5
segment_duration_seconds: 900
```

## Recording Format

Each camera writes segmented MKV files into its own directory:

```text
recordings/Entrance/Entrance_2026-07-10_14-15-00.mkv
```

The ffmpeg worker uses TCP RTSP transport and `-c copy`, so video is not transcoded.

## Tests and Lint

```bash
pytest
ruff check backend
black --check backend
```
