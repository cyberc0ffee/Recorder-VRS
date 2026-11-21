from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends

from app.api.dependencies import get_cleanup_service
from app.schemas.api import CleanupRead
from app.services.cleanup_service import CleanupService

router = APIRouter(prefix="/cleanup", tags=["cleanup"])


@router.post("", response_model=CleanupRead)
def run_cleanup(cleanup_service: CleanupService = Depends(get_cleanup_service)) -> CleanupRead:
    return CleanupRead.model_validate(asdict(cleanup_service.run_once()))
