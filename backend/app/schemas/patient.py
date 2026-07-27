from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.enums import Gender, PatientStatus


class PatientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    dob: date
    gender: Gender


class PatientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    dob: date | None = None
    gender: Gender | None = None
    status: PatientStatus | None = None


class PatientOut(BaseModel):
    id: UUID
    mrn: str
    name: str
    dob: date
    gender: Gender
    status: PatientStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PatientCounts(BaseModel):
    active: int
    pending: int
    inactive: int


class PatientListResponse(BaseModel):
    items: list[PatientOut]
    total: int
    counts: PatientCounts
