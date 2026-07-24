from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.call import CallStatus


class CallCreate(BaseModel):
    case_id: UUID
    phone_number: str = Field(min_length=1, max_length=20)
    transcript: str | None = None


class CallOut(BaseModel):
    id: UUID
    case_id: UUID
    phone_number: str
    transcript: str | None
    status: CallStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
