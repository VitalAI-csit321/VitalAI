from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints

from app.models.task import TaskCategory
from app.schemas.enums import TaskPriority, TaskStatus, TaskType, UserRole

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class HumanReviewTaskOut(BaseModel):
    id: UUID
    created_at: datetime
    # The contact; None for an item about a case (case_close), see episode_id.
    case_id: UUID | None
    episode_id: UUID | None = None
    triage_id: UUID | None
    task_type: TaskType
    status: TaskStatus
    priority: TaskPriority
    target_role: UserRole | None
    assigned_to: UUID | None
    notes: str | None
    approval_id: UUID | None = None
    inbox_task_id: UUID | None = None
    details: dict | None = None
    # Filled by the list endpoint only (human_review_service.describe_tasks).
    contact_reason: str | None = None
    patient_name: str | None = None
    created_by: str | None = None
    assigned_to_name: str | None = None
    owner_label: str | None = None
    channel: str | None = None
    due_at: datetime | None = None
    candidates: list[dict] | None = None
    case_title: str | None = None
    case_candidates: list[dict] | None = None

    model_config = {"from_attributes": True}


class HumanReviewTaskListResponse(BaseModel):
    items: list[HumanReviewTaskOut]
    total: int


class WorkflowDailyCount(BaseModel):
    day: str
    value: int


class HumanReviewCompleteBody(BaseModel):
    notes: str | None = None


class HumanReviewNoteBody(BaseModel):
    notes: NonBlank


class HumanReviewRerouteBody(BaseModel):
    category: TaskCategory


class HumanReviewLinkPatientBody(BaseModel):
    patient_id: UUID | None  # None: "None of these"


class HumanReviewReassignBody(BaseModel):
    doctor_id: UUID


class HumanReviewChooseCaseBody(BaseModel):
    episode_id: UUID | None  # None: a new case


class HumanReviewCaseCloseBody(BaseModel):
    close: bool
    note: str | None = Field(default=None, max_length=2000)


class HumanReviewTaskCreate(BaseModel):
    task_type: TaskType
    priority: TaskPriority = TaskPriority.MEDIUM
    assigned_to: UUID | None = None
    reviewed: bool = False
    notes: str | None = None
    contact_reason: str = Field(min_length=1)
