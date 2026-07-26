from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.call import CallStatus
from app.models.routing import RoutingAction
from app.models.task import TaskPriority
from app.models.triage import TriageCategory


class CallCreate(BaseModel):
    case_id: UUID
    phone_number: str = Field(min_length=1, max_length=20)
    transcript: str | None = None


class CallRouteRequest(BaseModel):
    keywords: list[str] = Field(default_factory=list)
    patient_priority_flags: list[str] = Field(default_factory=list)


class CallRoutingOverride(BaseModel):
    category: TriageCategory
    reason: str = Field(min_length=3, max_length=500)


class CallEscalateRequest(BaseModel):
    assigned_to: UUID | None = None
    reason: str | None = Field(default=None, max_length=500)


class CallOut(BaseModel):
    id: UUID
    case_id: UUID
    phone_number: str
    transcript: str | None
    status: CallStatus
    triage_id: UUID | None
    routing_id: UUID | None
    urgency_tier: TriageCategory | None
    target_queue: str | None
    routing_overridden: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CallRouteOut(BaseModel):
    call: CallOut
    category: TriageCategory
    confidence: float
    rationale: str
    routing_action: RoutingAction
    target_queue: str
    escalated: bool


class CallEscalationOut(BaseModel):
    call: CallOut
    task_id: UUID
    task_priority: TaskPriority
    target_queue: str
    handover_context: dict
