from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.enums import RoutingAction


class RoutingCreate(BaseModel):
    triage_id: UUID


class RoutingOut(BaseModel):
    id: UUID
    case_id: UUID
    triage_id: UUID
    action: RoutingAction
    target_queue: str
    escalated: bool
    created_at: datetime

    model_config = {"from_attributes": True}
