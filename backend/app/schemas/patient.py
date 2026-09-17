from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.enums import Gender, PatientStatus


class PatientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    dob: date
    gender: Gender
    address: str | None = None
    indigenous_status: str | None = None
    preferred_language: str | None = None
    phone: str | None = None
    email: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    preferred_communication: str | None = None
    best_time_to_contact: str | None = None
    known_conditions: str | None = None
    current_medications: str | None = None
    allergies: str | None = None
    insurance_provider: str | None = None
    policy_number: str | None = None
    group_number: str | None = None
    insurance_expiry: date | None = None
    medicare_number: str | None = None
    concession_card: str | None = None


class PatientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    dob: date | None = None
    gender: Gender | None = None
    status: PatientStatus | None = None
    address: str | None = None
    indigenous_status: str | None = None
    preferred_language: str | None = None
    phone: str | None = None
    email: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    preferred_communication: str | None = None
    best_time_to_contact: str | None = None
    known_conditions: str | None = None
    current_medications: str | None = None
    allergies: str | None = None
    insurance_provider: str | None = None
    policy_number: str | None = None
    group_number: str | None = None
    insurance_expiry: date | None = None
    medicare_number: str | None = None
    concession_card: str | None = None


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
