from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import ApprovalRequest, ApprovalStatus
from app.models.base import utcnow
from app.models.human_review import TaskType
from app.models.task import Task
from app.models.user import User
from app.services import review_routing
from app.services.audit_service import record_event

DRAFT_REPLY = "email.draft_reply"


def _draft_reason(payload: dict) -> str:
    if payload.get("delivery_error"):
        return f"The reply could not be sent automatically: {payload['delivery_error']}"
    if payload.get("critic_reason"):
        return f"The policy check held this reply: {payload['critic_reason']}"
    return "A drafted reply is waiting for approval before it is sent."


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

    # The item before the audit event: the item's insert locks the Task row
    # (its foreign key) and record_event takes the audit chain lock, and
    # write_reply takes them in that order too. The other order deadlocks.
    task_id = payload.get("task_id") if action_type == DRAFT_REPLY else None
    task = await db.get(Task, UUID(str(task_id)), populate_existing=True) if task_id else None
    # Already answered (a Write reply while this was drafting): nothing to
    # approve, so no item. The request itself stays, a paused thread waits on it.
    if task is not None and not task.draft_sent:
        await review_routing.open_item(
            db,
            kind=TaskType.DRAFT_APPROVAL,
            inbox_task=task,
            reason=_draft_reason(payload),
            actor=requested_by,
            approval_id=request.id,
            # The category at draft time, so a later category override
            # (task_service.override_task) can't launder a clinical reply
            # through a relabel; see human_review_service.is_clinical.
            details={"category": task.category.value if task.category else None},
        )

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
    # with_for_update: two concurrent approve()/reject() calls on the same
    # request must not both pass the PENDING check below. Without the lock,
    # a blocked commit() unblocks after the first commit and Postgres
    # silently re-applies it (WHERE id = :id still matches), overwriting the
    # already-decided row instead of raising ApprovalAlreadyDecidedError.
    # populate_existing=True: a caller that already ran a plain db.get() on
    # this id earlier in the same session (e.g. the row-level ownership
    # check in app/routes/approvals.py) has it in the identity map. The FOR
    # UPDATE query still runs and takes the lock (SQLAlchemy 2.0 skips the
    # identity-map shortcut when with_for_update is set), but the row it
    # returns is not copied onto the already-loaded object unless forced to.
    # Without this, the stale status (still PENDING) passes the check below
    # even though another session already decided and committed.
    request = await db.get(
        ApprovalRequest, approval_id, with_for_update=True, populate_existing=True
    )
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
    await review_routing.close_for_approval(
        db, request.id, actor=decided_by, approved=True, notes=notes
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
    # with_for_update + populate_existing: see the matching comment in
    # approve() above.
    request = await db.get(
        ApprovalRequest, approval_id, with_for_update=True, populate_existing=True
    )
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
    await review_routing.close_for_approval(
        db, request.id, actor=decided_by, approved=False, notes=notes
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
