from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.episode import EpisodeStatus


class EpisodeCreate(BaseModel):
    patient_id: UUID
    title: str = Field(min_length=1, max_length=255)
    doctor_id: UUID | None = None  # default: the patient's doctor


class EpisodeUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    doctor_id: UUID | None = None


class EpisodeCloseBody(BaseModel):
    note: str = Field(max_length=2000)


class StaffContactBody(BaseModel):
    reason: str = Field(min_length=1, max_length=255)


class EpisodeMoveBody(BaseModel):
    kind: Literal["contact", "appointment", "consent"]
    item_id: UUID
    target_episode_id: UUID | None = None  # None: a new case titled new_title
    new_title: str | None = Field(default=None, max_length=255)
    # Only for a contact with no confirmed patient yet (a voicemail): who it is.
    patient_id: UUID | None = None


class EpisodeOut(BaseModel):
    id: UUID
    patient_id: UUID
    patient_name: str | None = None
    title: str
    status: EpisodeStatus
    doctor_id: UUID | None
    doctor_name: str | None = None
    opened_at: datetime
    closed_at: datetime | None
    outcome_note: str | None
    last_activity_at: datetime

    model_config = {"from_attributes": True}


class EpisodeListResponse(BaseModel):
    items: list[EpisodeOut]
    total: int


class TimelineEntry(BaseModel):
    kind: Literal["contact", "appointment", "consent", "review"]
    id: UUID
    at: datetime
    label: str
    status: str | None = None
    # The contact the entry hangs off, and the inbox message a contact opens.
    contact_id: UUID | None = None
    inbox_task_id: UUID | None = None


class EpisodeDetailOut(EpisodeOut):
    timeline: list[TimelineEntry]
