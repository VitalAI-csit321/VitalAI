from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.enums import RoutingAction, TriageCategory


class TriageRequest(BaseModel):
    case_id: UUID
    contact_reason: str
    keywords: list[str] = Field(default_factory=list)
    patient_priority_flags: list[str] = Field(default_factory=list)


class TriageOut(BaseModel):
    id: UUID
    case_id: UUID
    category: TriageCategory
    confidence: float
    rationale: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TriageResponse(BaseModel):
    """API response combining triage + computed routing intent.
    The actual RoutingDecision row is created by the routing endpoint.
    """

    triage_id: UUID
    case_id: UUID
    category: TriageCategory
    confidence: float
    rationale: str
    routing_action: RoutingAction
    target_queue: str
    escalated: bool
