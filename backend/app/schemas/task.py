from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.task import TaskItemStatus, TaskPriority, TaskSource


class TaskCreate(BaseModel):
    case_id: UUID
    source: TaskSource
    priority: TaskPriority = TaskPriority.MEDIUM
    assigned_to: UUID | None = None


class TaskUpdate(BaseModel):
    status: TaskItemStatus | None = None
    priority: TaskPriority | None = None
    assigned_to: UUID | None = None


class TaskOut(BaseModel):
    id: UUID
    case_id: UUID
    assigned_to: UUID | None
    source: TaskSource
    priority: TaskPriority
    status: TaskItemStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaskColumnCounts(BaseModel):
    pending: int
    in_progress: int
    escalated: int
    completed: int


class TaskBoardOut(BaseModel):
    columns: dict[str, list[TaskOut]]
    counts: TaskColumnCounts
