from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.enums import TaskPriority, TaskStatus, TaskType, UserRole


class HumanReviewTaskOut(BaseModel):
    id: UUID
    created_at: datetime
    case_id: UUID
    triage_id: UUID | None
    task_type: TaskType
    status: TaskStatus
    priority: TaskPriority
    target_role: UserRole | None
    assigned_to: UUID | None
    notes: str | None

    model_config = {"from_attributes": True}


class HumanReviewTaskListResponse(BaseModel):
    items: list[HumanReviewTaskOut]
    total: int


class WorkflowDailyCount(BaseModel):
    day: str
    value: int


class HumanReviewCompleteBody(BaseModel):
    notes: str | None = None


class HumanReviewTaskCreate(BaseModel):
    task_type: TaskType
    priority: TaskPriority = TaskPriority.MEDIUM
    assigned_to: UUID | None = None
    reviewed: bool = False
    notes: str | None = None
    contact_reason: str = Field(min_length=1)
