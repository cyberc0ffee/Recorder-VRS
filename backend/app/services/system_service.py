from __future__ import annotations

import os
from dataclasses import asdict
from typing import Any

from app.services.storage_service import StorageService
from app.workers.manager import WorkerManager

try:
    import psutil
except ImportError:  # pragma: no cover - depends on optional runtime package
    psutil = None


class SystemService:
    def __init__(self, storage_service: StorageService, worker_manager: WorkerManager) -> None:
        self.storage_service = storage_service
        self.worker_manager = worker_manager

    def snapshot(self) -> dict[str, Any]:
        worker_statuses = self.worker_manager.all_statuses()
        recording_count = sum(1 for status in worker_statuses.values() if status["recording"])
        online_count = sum(1 for status in worker_statuses.values() if status["online"])

        cpu_percent = None
        ram: dict[str, Any] | None = None
        if psutil is not None:
            cpu_percent = psutil.cpu_percent(interval=0.0)
            virtual_memory = psutil.virtual_memory()
            ram = {
                "total_bytes": virtual_memory.total,
                "used_bytes": virtual_memory.used,
                "free_bytes": virtual_memory.available,
                "percent": virtual_memory.percent,
            }

        return {
            "process_id": os.getpid(),
            "cpu_percent": cpu_percent,
            "ram": ram,
            "disk": asdict(self.storage_service.disk_stats()),
            "cameras_online": online_count,
            "cameras_offline": max(0, len(worker_statuses) - online_count),
            "recording_cameras": recording_count,
            "workers": worker_statuses,
        }
