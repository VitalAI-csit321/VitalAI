from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.task import TaskItemStatus, TaskPriority, TaskSource


class TaskCreate(BaseModel):
    case_id: UUID
    assigned_to: UUID | None = None
    source: TaskSource
    priority: TaskPriority = TaskPriority.MEDIUM


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
