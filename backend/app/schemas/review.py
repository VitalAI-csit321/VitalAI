from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.human_review import TaskStatus, TaskType


class ReviewTaskCreate(BaseModel):
    case_id: UUID
    task_type: TaskType
    triage_id: UUID | None = None
    notes: str | None = None


class ReviewTaskUpdate(BaseModel):
    """Partial update. Every field optional — omitted fields are left alone."""

    status: TaskStatus | None = None
    assigned_to: UUID | None = None
    notes: str | None = Field(default=None, max_length=4000)


class ReviewTaskOut(BaseModel):
    id: UUID
    case_id: UUID
    triage_id: UUID | None
    task_type: TaskType
    status: TaskStatus
    assigned_to: UUID | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
