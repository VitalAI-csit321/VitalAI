from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.enums import ConsentStatus


class ConsentCreate(BaseModel):
    case_id: UUID
    consent_type: str = Field(default="administrative", max_length=50)
    notes: str | None = None


class ConsentOut(BaseModel):
    id: UUID
    case_id: UUID
    status: ConsentStatus
    captured_at: datetime | None
    consent_type: str
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
