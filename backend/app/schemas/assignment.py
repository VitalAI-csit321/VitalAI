from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AssignmentCreate(BaseModel):
    doctor_id: UUID
    patient_id: UUID


class AssignmentOut(BaseModel):
    doctor_id: UUID
    patient_id: UUID
    assigned_by: UUID
    assigned_at: datetime

    model_config = {"from_attributes": True}
