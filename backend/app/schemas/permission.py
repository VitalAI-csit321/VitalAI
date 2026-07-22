from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class PermissionGrantCreate(BaseModel):
    permission: str


class PermissionGrantOut(BaseModel):
    user_id: UUID
    permission: str
    granted_by: UUID
    granted_at: datetime

    model_config = {"from_attributes": True}
