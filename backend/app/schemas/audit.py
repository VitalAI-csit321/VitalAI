from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class AuditEventOut(BaseModel):
    id: UUID
    case_id: UUID | None
    actor_id: UUID | None
    actor_label: str | None
    action: str
    details: dict[str, Any]
    timestamp: datetime

    model_config = {"from_attributes": True}
