from uuid import UUID

from pydantic import BaseModel


class DoctorOut(BaseModel):
    id: UUID
    full_name: str
    department: str | None

    model_config = {"from_attributes": True}
