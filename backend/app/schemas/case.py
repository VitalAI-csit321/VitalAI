from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.enums import IntakeStatus


class IntakeCreate(BaseModel):
    patient_id: UUID
    contact_reason: str = Field(min_length=1)
    contact_channel: str = Field(min_length=1, max_length=50)
    notes: str | None = None


class IntakeStatusUpdate(BaseModel):
    status: IntakeStatus


class IntakeCaseOut(BaseModel):
    id: UUID
    patient_id: UUID | None
    patient_name: str | None
    contact_reason: str
    contact_channel: str
    notes: str | None
    status: IntakeStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class IntakeCaseListResponse(BaseModel):
    items: list[IntakeCaseOut]
    total: int
    limit: int
    offset: int
