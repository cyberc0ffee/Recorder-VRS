# RTSP Recorder - Software Specification

## 1. Project Overview

RTSP Recorder is a professional Network Video Recorder (NVR) written in Python.

The objective is to build a lightweight, reliable and modular system capable of recording dozens of RTSP cameras continuously without transcoding.

The software must prioritize:

* Stability
* Reliability
* Maintainability
* Performance
* Easy deployment
* Low CPU usage
* Scalability

The application is intended to run on Ubuntu Server but must also support macOS for development.

---

## 2. Technology Stack

### Backend

* Python 3.12+
* FastAPI
* Uvicorn
* SQLite
* SQLAlchemy (future migration)
* Pydantic v2
* ffmpeg

### Frontend

* Vue 3
* Vite
* Pinia
* Vue Router

### Database

SQLite

Future:

* PostgreSQL

---

## 3. General Architecture

The application must follow a layered architecture.

```text
Frontend (Vue)
    |
REST API (FastAPI)
    |
Business Services
    |
Workers
    |
FFmpeg
    |
Filesystem
```

Every layer must be independent.

Business logic must never be inside API endpoints.

---

## 4. Main Goals

The software must be capable of managing between 10 and 100 RTSP cameras simultaneously.

Requirements:

* continuous recording
* automatic restart
* automatic recovery
* low CPU usage
* automatic storage cleanup
* web interface
* logging
* configuration management

---

## 5. Recording

The software must never transcode video unless explicitly requested.

Default ffmpeg command:

* codec copy
* TCP transport
* MKV container
* segmented recording

Segment duration:

15 minutes

File format:

```text
CameraName_YYYY-MM-DD_HH-MM-SS.mkv
```

Example:

```text
Entrance_2026-07-10_14-15-00.mkv
```

---

## 6. Why MKV

The application must record using MKV instead of MP4.

Reasons:

* survives unexpected shutdowns
* survives power failures
* survives process crashes
* lower corruption risk

---

## 7. Camera Worker

Every camera must have its own dedicated worker.

Each worker owns:

* ffmpeg process
* watchdog
* status
* statistics

One crashed worker must never affect other cameras.

---

## 8. Watchdog

Each camera worker must continuously verify:

* ffmpeg alive
* RTSP reachable
* file growing
* disk availability
* ffmpeg exit code

If a failure occurs:

1. log event
2. wait configurable delay
3. restart ffmpeg

Maximum downtime should be only a few seconds.

---

## 9. Automatic Startup

When the application starts:

* load configuration
* load database
* recreate workers
* automatically restart enabled cameras

No manual intervention should be required.

---

## 10. Storage

Configurable recording path.

Example:

Ubuntu:

```text
/mnt/videos
```

macOS:

```text
~/Movies/RTSPRecorder
```

Each camera has its own directory.

Example:

```text
recordings/
Entrance/
Garage/
Reception/
```

---

## 11. Retention

Automatic deletion of old recordings.

Configurable.

Example:

30 days

Cleanup must execute periodically.

Deletion must never block recordings.

---

## 12. Disk Monitoring

Monitor:

* total size
* free space
* used space

If free space goes below configured threshold:

* log warning
* stop starting new recordings
* keep existing recordings alive when possible

---

## 13. Logging

Every component must use structured logging.

Levels:

* DEBUG
* INFO
* WARNING
* ERROR
* CRITICAL

Each camera also owns:

```text
logs/ffmpeg.log
```

---

## 14. Database

SQLite.

Tables:

### Cameras

* id
* name
* rtsp_url
* enabled
* autostart
* created_at

### Recordings

* id
* camera_id
* filename
* duration
* size
* start_time
* end_time

### Events

* id
* timestamp
* level
* message
* camera_id

---

## 15. REST API

Example endpoints:

```text
GET /api/cameras
POST /api/cameras
DELETE /api/cameras/{id}
POST /api/cameras/{id}/start
POST /api/cameras/{id}/stop
GET /api/system
GET /api/events
POST /api/cleanup
```

FastAPI automatic documentation must remain enabled.

---

## 16. Frontend

Vue 3.

Modern responsive interface.

Dashboard must show:

* CPU
* RAM
* Disk
* Cameras online
* Cameras offline
* Recording cameras
* Recent events

---

## 17. Camera Management

For every camera display:

* Name
* IP
* RTSP URL
* Status
* Recording state
* Restart counter
* Last error

Buttons:

* Start
* Stop
* Edit
* Delete

---

## 18. Recording Browser

Future implementation.

Must include:

* calendar
* timeline
* recording list
* download
* delete
* integrated playback

---

## 19. Security

Future authentication.

Roles:

* Administrator
* Operator
* Viewer

HTTPS support.

JWT authentication.

Audit logs.

---

## 20. Configuration

YAML configuration.

Example:

* recording path
* retention
* minimum disk
* ffmpeg binary
* restart timeout
* web port
* logging level

Configuration reload without restarting the application is desirable.

---

## 21. Code Style

Use:

* type hints
* docstrings
* Black formatting
* Ruff
* modular architecture
* dependency injection where appropriate

Avoid:

* global variables
* duplicated code
* business logic inside API routes

---

## 22. Testing

Unit tests.

Integration tests.

Mock ffmpeg where possible.

Target coverage:

80%+

---

## 23. Deployment

Support:

* Ubuntu
* Docker
* Docker Compose
* systemd

Future:

* Kubernetes

---

## 24. Future Features

Planned features:

* ONVIF discovery
* ONVIF events
* Motion Detection
* AI object detection
* Face Recognition
* License Plate Recognition
* WebRTC
* HLS
* GPU acceleration
* Telegram notifications
* Email alerts
* Multi-user support
* High Availability
* NAS integration
* S3 storage
* Automatic backups
* Cluster mode
* Recording encryption
* Camera health reports
* Storage prediction
* Mobile interface

---

## 25. Development Philosophy

This software must be developed as if it were a commercial product.

Primary priorities:

1. Reliability
2. Stability
3. Simplicity
4. Performance
5. Maintainability

Every architectural decision should favor long-term maintainability over short-term convenience.

The codebase must be clean, modular and extensible so that new features can be added without rewriting existing components.

No feature should compromise recording reliability.

Continuous recording is the highest priority of the entire application.
