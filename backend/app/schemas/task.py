from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.task import TaskItemStatus, TaskPriority, TaskSource


class TaskCreate(BaseModel):
    case_id: UUID
    assigned_to: UUID | None = None
    source: TaskSource
    priority: TaskPriority = TaskPriority.MEDIUM


class TaskUpdate(BaseModel):
    status: TaskItemStatus | None = None
    assigned_to: UUID | None = None
    priority: TaskPriority | None = None


class TaskOut(BaseModel):
    id: UUID
    case_id: UUID
    call_id: UUID | None
    assigned_to: UUID | None
    source: TaskSource
    priority: TaskPriority
    status: TaskItemStatus
    target_queue: str | None
    handover_context: str | None
    created_at: datetime
    updated_at: datetime

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
