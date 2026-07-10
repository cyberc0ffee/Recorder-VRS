from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_event_service
from app.schemas.api import EventRead
from app.services.event_service import EventService


router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[EventRead])
def list_events(
    limit: int = Query(default=100, ge=1, le=500),
    event_service: EventService = Depends(get_event_service),
) -> list[EventRead]:
    return [EventRead.model_validate(event.__dict__) for event in event_service.list_recent(limit)]

