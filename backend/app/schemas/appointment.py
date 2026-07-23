from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.enums import AppointmentStatus


class AppointmentCreate(BaseModel):
    doctor_id: UUID
    case_id: UUID
    time_slot: datetime


class AppointmentReschedule(BaseModel):
    time_slot: datetime


class AppointmentOut(BaseModel):
    id: UUID
    case_id: UUID
    doctor_id: UUID
    time_slot: datetime
    status: AppointmentStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AppointmentListResponse(BaseModel):
    items: list[AppointmentOut]
    total: int
