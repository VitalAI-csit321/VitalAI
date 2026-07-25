from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.enums import ApprovalStatus


class ApprovalRequestOut(BaseModel):
    id: UUID
    created_at: datetime
    action_type: str
    case_id: UUID | None
    payload: dict
    external_ref: str | None
    requested_by_id: UUID | None
    requested_by_label: str
    status: ApprovalStatus
    decided_by_id: UUID | None
    decided_at: datetime | None
    resolved_payload: dict | None
    decision_notes: str | None

    model_config = {"from_attributes": True}


class ApprovalListResponse(BaseModel):
    items: list[ApprovalRequestOut]
    total: int


class ApprovalApproveBody(BaseModel):
    resolved_payload: dict | None = None
    notes: str | None = None


class ApprovalRejectBody(BaseModel):
    notes: str | None = None
