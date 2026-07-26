from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.task import TaskCategory, TaskItemStatus, TaskPriority, TaskSource
from app.models.user import UserRole


class TaskCreate(BaseModel):
    case_id: UUID
    assigned_to: UUID | None = None
    source: TaskSource
    priority: TaskPriority = TaskPriority.MEDIUM


class TaskUpdate(BaseModel):
    status: TaskItemStatus | None = None
    assigned_to: UUID | None = None
    priority: TaskPriority | None = None


class TaskOverrideRequest(BaseModel):
    category: TaskCategory
    reason: str = Field(min_length=3, max_length=500)


class TaskEscalateRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class TaskOut(BaseModel):
    id: UUID
    case_id: UUID
    call_id: UUID | None
    assigned_to: UUID | None
    source: TaskSource
    category: TaskCategory | None
    target_role: UserRole | None
    priority: TaskPriority
    status: TaskItemStatus
    target_queue: str | None
    handover_context: str | None
    draft_text: str | None
    draft_sent: bool
    created_at: datetime
    updated_at: datetime
    # Joined from the linked Email/Call, not a real Task column, populated
    # only by list_tasks() for the Escalations board's identification needs.
    # Other TaskOut-returning routes leave these None.
    subject: str | None = None
    from_name: str | None = None

    model_config = {"from_attributes": True}


class TaskCommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class TaskCommentOut(BaseModel):
    id: UUID
    task_id: UUID
    author_id: UUID
    body: str
    created_at: datetime

    model_config = {"from_attributes": True}
