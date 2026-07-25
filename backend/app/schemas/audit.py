from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, computed_field

from app.services.audit_service import risk_level_from_score


class AuditEventOut(BaseModel):
    id: UUID
    case_id: UUID | None
    actor_id: UUID | None
    actor_label: str | None
    actor_role: str | None
    action: str
    details: dict[str, Any]
    timestamp: datetime
    risk_score: int | None
    outcome: str | None
    ip_address: str | None
    session_id: str | None
    event_hash: str | None
    predecessor_hash: str | None

    model_config = {"from_attributes": True}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def risk_level(self) -> str:
        return risk_level_from_score(self.risk_score)


class AuditEventListResponse(BaseModel):
    items: list[AuditEventOut]
    total: int
