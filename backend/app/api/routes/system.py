from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_system_service
from app.schemas.api import SystemRead
from app.services.system_service import SystemService


router = APIRouter(prefix="/system", tags=["system"])


@router.get("", response_model=SystemRead)
def get_system(system_service: SystemService = Depends(get_system_service)) -> SystemRead:
    return SystemRead.model_validate(system_service.snapshot())

