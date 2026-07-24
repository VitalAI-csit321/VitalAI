from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import ApprovalRequest, ApprovalStatus
from app.models.base import utcnow
from app.models.user import User
from app.services.audit_service import record_event


class ApprovalNotFoundError(Exception):
    """Raised when approval_id doesn't reference an existing ApprovalRequest."""


class ApprovalAlreadyDecidedError(Exception):
    """Raised when approve/reject is called on a request that isn't pending."""


class ApprovalNotGrantedError(Exception):
    """Raised by ensure_approved() when a request hasn't been approved."""


async def create_approval_request(
    db: AsyncSession,
    action_type: str,
    payload: dict,
    case_id: UUID | None = None,
    requested_by: User | None = None,
    external_ref: str | None = None,
) -> ApprovalRequest:
    request = ApprovalRequest(
        action_type=action_type,
        payload=payload,
        case_id=case_id,
        external_ref=external_ref,
        requested_by_id=requested_by.id if requested_by else None,
        requested_by_label=requested_by.email if requested_by else "system",
    )
    db.add(request)
    await db.flush()  # populate request.id before referencing it below

    await record_event(
        db,
        actor=requested_by,
        case_id=case_id,
        action="governance.approval_requested",
        details={"approval_id": str(request.id), "action_type": action_type},
    )
    await db.commit()
    await db.refresh(request)
    return request


async def approve(
    db: AsyncSession,
    approval_id: UUID,
    decided_by: User,
    resolved_payload: dict | None = None,
    notes: str | None = None,
) -> ApprovalRequest:
    request = await db.get(ApprovalRequest, approval_id)
    if request is None:
        raise ApprovalNotFoundError(f"No approval request with id {approval_id}")
    if request.status != ApprovalStatus.PENDING:
        raise ApprovalAlreadyDecidedError(
            f"Approval request {approval_id} already {request.status.value}"
        )

    request.status = ApprovalStatus.APPROVED
    request.decided_by_id = decided_by.id
    request.decided_at = utcnow()
    request.resolved_payload = resolved_payload
    request.decision_notes = notes

    await record_event(
        db,
        actor=decided_by,
        case_id=request.case_id,
        action="governance.approval_approved",
        details={"approval_id": str(request.id), "action_type": request.action_type},
    )
    await db.commit()
    await db.refresh(request)
    return request


async def reject(
    db: AsyncSession,
    approval_id: UUID,
    decided_by: User,
    notes: str | None = None,
) -> ApprovalRequest:
    request = await db.get(ApprovalRequest, approval_id)
    if request is None:
        raise ApprovalNotFoundError(f"No approval request with id {approval_id}")
    if request.status != ApprovalStatus.PENDING:
        raise ApprovalAlreadyDecidedError(
            f"Approval request {approval_id} already {request.status.value}"
        )

    request.status = ApprovalStatus.REJECTED
    request.decided_by_id = decided_by.id
    request.decided_at = utcnow()
    request.decision_notes = notes

    await record_event(
        db,
        actor=decided_by,
        case_id=request.case_id,
        action="governance.approval_rejected",
        details={"approval_id": str(request.id), "action_type": request.action_type},
    )
    await db.commit()
    await db.refresh(request)
    return request


def ensure_approved(request: ApprovalRequest) -> None:
    """Raise unless `request` has been approved.

    Call this immediately before performing the sensitive action it gates.
    This is the enforcement point for the invariant that approval-checking
    lives in the caller, never in the AI/agent code itself.
    """
    if request.status != ApprovalStatus.APPROVED:
        raise ApprovalNotGrantedError(
            f"Approval request {request.id} is {request.status.value}, not approved"
        )


async def list_approvals(
    db: AsyncSession,
    status: ApprovalStatus | None = None,
    action_type: str | None = None,
    case_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ApprovalRequest], int]:
    query = select(ApprovalRequest)
    count_query = select(func.count()).select_from(ApprovalRequest)
    if status is not None:
        query = query.where(ApprovalRequest.status == status)
        count_query = count_query.where(ApprovalRequest.status == status)
    if action_type is not None:
        query = query.where(ApprovalRequest.action_type == action_type)
        count_query = count_query.where(ApprovalRequest.action_type == action_type)
    if case_id is not None:
        query = query.where(ApprovalRequest.case_id == case_id)
        count_query = count_query.where(ApprovalRequest.case_id == case_id)

    total = (await db.execute(count_query)).scalar_one()
    query = query.order_by(ApprovalRequest.created_at).limit(limit).offset(offset)
    items = (await db.execute(query)).scalars().all()
    return list(items), total


async def get_approval(db: AsyncSession, approval_id: UUID) -> ApprovalRequest | None:
    return await db.get(ApprovalRequest, approval_id)
