"""Review Queue items for messages already waiting when the queue shipped.

Migration 0037 added the queue but opened nothing for work that was held
before it, so a doctor saw those drafts in the Inbox without Approve and never
in the queue. At startup each live, still-open message gets the item the
current code would open for a new one; everything else keeps its inbox-only
treatment (voicemails, automatic messages, "no reply needed" verdicts).
Idempotent: a message that ever had an item of that
kind is skipped, so a closed item is never reopened.
"""

from typing import Any

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import ApprovalRequest, ApprovalStatus
from app.models.human_review import HumanReviewTask, TaskType
from app.models.task import Task, TaskItemStatus, TaskSource
from app.models.user import User, UserRole
from app.services import (
    approval_service,
    booking_service,
    email_conversation_service,
    identity_service,
    prescription_service,
    review_routing,
)

_OPEN = (TaskItemStatus.PENDING, TaskItemStatus.IN_PROGRESS, TaskItemStatus.ESCALATED)
_IDENTITY = {reason: outcome for outcome, reason in identity_service._HOLD_REASONS.items()}
# task_service.hold_for_staff's reasons, which open an agent_handover item; the
# booking hold for a patient with no doctor is the operator's.
_HANDOVERS: dict[str, UserRole | None] = {
    booking_service.NO_DOCTOR_REASON: UserRole.OPERATOR,
    booking_service.NO_SLOTS_REASON: None,
    **{reason: None for reason in email_conversation_service.STAFF_REASONS.values()},
}
_AGENT_FAILURE = "Automated handling stopped at "  # task_service.record_agent_failure


async def _item_for(db: AsyncSession, task: Task) -> tuple[TaskType, dict[str, Any]] | None:
    """(kind, open_item arguments) the current code would give this message, or None."""
    if task.draft_approval_id is not None and not task.draft_sent:
        approval = await db.get(ApprovalRequest, task.draft_approval_id)
        if approval is not None and approval.status == ApprovalStatus.PENDING:
            return TaskType.DRAFT_APPROVAL, {
                "reason": approval_service._draft_reason(approval.payload),
                "approval_id": approval.id,
                "details": {"category": task.category.value if task.category else None},
            }
    reason = task.handover_context
    if reason is None:
        return None
    if reason in _IDENTITY:
        details: dict[str, Any] = {"outcome": _IDENTITY[reason].value, "candidates": []}
        return TaskType.IDENTITY_REVIEW, {"reason": reason, "details": details}
    if reason in prescription_service.REQUEST_REASONS:
        return TaskType.PRESCRIPTION_REQUEST, {"reason": reason}
    if reason.startswith(_AGENT_FAILURE):
        return TaskType.AGENT_FAILURE, {"reason": reason}
    if reason in _HANDOVERS:
        return TaskType.AGENT_HANDOVER, {"reason": reason, "owner": _HANDOVERS[reason]}
    return None


async def backfill(db: AsyncSession, *, actor: User | None) -> int:
    """Open the missing items and commit. Returns how many were opened."""
    tasks = (
        (
            await db.execute(
                select(Task).where(
                    Task.deleted_at.is_(None),
                    Task.status.in_(_OPEN),
                    Task.source != TaskSource.CALL,
                    or_(Task.draft_approval_id.is_not(None), Task.handover_context.is_not(None)),
                )
            )
        )
        .scalars()
        .all()
    )
    opened = 0
    for task in tasks:
        found = await _item_for(db, task)
        if found is None:
            continue
        kind, arguments = found
        had_one = await db.scalar(
            select(
                exists().where(
                    HumanReviewTask.inbox_task_id == task.id, HumanReviewTask.task_type == kind
                )
            )
        )
        if had_one:
            continue
        await review_routing.open_item(db, kind=kind, inbox_task=task, actor=actor, **arguments)
        opened += 1
    await db.commit()
    return opened
