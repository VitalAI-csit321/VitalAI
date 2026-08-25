from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.models.task import TaskCategory, TaskPriority
from app.models.user import UserRole
from app.services.task_routing_gate import TaskRoutingOutcome


class EmailIngestRequest(BaseModel):
    sender: EmailStr
    recipient: EmailStr
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1)
    case_id: UUID | None = None  # None creates a new IntakeCase

    # Set by the Outlook connector, absent for directly-ingested mail.
    # received_at carries the mailbox's own timestamp so a polled email keeps
    # when it actually arrived rather than when this system got round to it.
    external_id: str | None = None
    external_source: str | None = None
    received_at: datetime | None = None


class EmailOut(BaseModel):
    id: UUID
    case_id: UUID
    sender: str
    recipient: str
    subject: str
    body: str
    received_at: datetime
    external_id: str | None = None
    external_source: str | None = None

    model_config = {"from_attributes": True}


class EmailIngestResult(BaseModel):
    email: EmailOut
    task_id: UUID
    category: TaskCategory
    confidence: float
    target_role: UserRole
    priority: TaskPriority
    outcome: TaskRoutingOutcome
    override_reason: str | None
    draft_text: str | None = None
    approval_id: str | None = None
    sent: bool = False
    blocked: bool = False
