from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.enums import ConsentStatus


class ConsentCreate(BaseModel):
    case_id: UUID
    consent_type: str = Field(default="administrative", max_length=50)
    notes: str | None = None


class ConsentFormCheck(BaseModel):
    label: str
    checked: bool


class ConsentFormSnapshot(BaseModel):
    checks: list[ConsentFormCheck]
    # None when an online registration consent is left for the patient to
    # sign at the clinic, or after the provisional purge removed it.
    signature: str | None = None


class ConsentCaptureIn(BaseModel):
    form_snapshot: ConsentFormSnapshot | None = None


class ConsentVerifyIn(BaseModel):
    """Staff finishing an online registration consent at the clinic: one
    answer per statement already on the record, and the signature if the
    patient did not sign online."""

    checks: list[bool] | None = None
    signature: str | None = Field(
        default=None, max_length=200_000, pattern=r"^data:image/png;base64,[A-Za-z0-9+/=]+$"
    )


class ConsentOut(BaseModel):
    id: UUID
    case_id: UUID
    status: ConsentStatus
    captured_at: datetime | None
    consent_type: str
    notes: str | None
    form_snapshot: ConsentFormSnapshot | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConsentQueueRow(BaseModel):
    """One row of the staff consent queue: the record, plus who it is for."""

    id: UUID
    case_id: UUID
    patient_name: str | None
    consent_type: str
    status: ConsentStatus
    created_at: datetime
    captured_at: datetime | None


class ConsentQueueResponse(BaseModel):
    items: list[ConsentQueueRow]
    total: int
