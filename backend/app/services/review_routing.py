"""Review Queue items the system opens itself (review queue spec, 2026-09-29).

Every hook that holds work for a person calls open_item: a held draft, a
low-confidence or disputed routing, an unconfirmed sender, a stopped or
handed-over agent run, a complaint. The owner is decided here, once, at
creation; afterwards only Escalate and Reassign move an item
(human_review_service).

Imports no service that imports it back: approval_service and task_service
both call in here.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case import IntakeCase
from app.models.human_review import HumanReviewTask, TaskPriority, TaskStatus, TaskType
from app.models.task import Task
from app.models.task import TaskPriority as InboxPriority
from app.models.user import User, UserRole
from app.services import booking_service
from app.services.audit_service import record_event

OPEN_STATUSES = (TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.ESCALATED)

_PRIORITY = {
    InboxPriority.URGENT: TaskPriority.HIGH,
    InboxPriority.HIGH: TaskPriority.HIGH,
    InboxPriority.MEDIUM: TaskPriority.MEDIUM,
    InboxPriority.LOW: TaskPriority.LOW,
}

# Kinds owned by whoever owns the message itself (spec section 5).
_FOLLOWS_MESSAGE = frozenset({TaskType.DRAFT_APPROVAL, TaskType.AGENT_HANDOVER})


async def owner_for(
    db: AsyncSession, *, inbox_task: Task, kind: TaskType
) -> tuple[UserRole, UUID | None]:
    """(target_role, assigned_to) for a new item."""
    if kind == TaskType.IDENTITY_REVIEW:
        return UserRole.FRONT_DESK, None
    if kind == TaskType.CASE_CHOICE:
        # The open cases may have different doctors; the patient's own decides.
        case = await db.get(IntakeCase, inbox_task.case_id)
        doctor = (
            await booking_service.doctor_for_patient(db, case.patient_id)
            if case is not None and case.patient_id is not None
            else None
        )
        return (UserRole.DOCTOR, doctor[0]) if doctor else (UserRole.OPERATOR, None)
    if kind not in _FOLLOWS_MESSAGE:
        return UserRole.OPERATOR, None
    role = inbox_task.target_role or UserRole.OPERATOR
    if role != UserRole.DOCTOR:
        return role, None
    case = await db.get(IntakeCase, inbox_task.case_id)
    # The case's doctor, else the patient's (M4). Doctor work for a patient
    # without one (the unidentified, or registered before M4) is the operator's.
    doctor = await booking_service.doctor_for_contact(db, case) if case is not None else None
    return (UserRole.DOCTOR, doctor[0]) if doctor else (UserRole.OPERATOR, None)


async def open_item(
    db: AsyncSession,
    *,
    kind: TaskType,
    inbox_task: Task,
    reason: str,
    actor: User | None,
    approval_id: UUID | None = None,
    details: dict | None = None,
    priority: TaskPriority | None = None,
    owner: UserRole | None = None,
) -> HumanReviewTask:
    """The one open item for this message and kind, created if missing.

    A re-run node gets the existing item back. Flushes, never commits: the
    caller's commit keeps the item and the change it is about together.
    """
    existing = (
        await db.execute(
            select(HumanReviewTask).where(
                HumanReviewTask.inbox_task_id == inbox_task.id,
                HumanReviewTask.task_type == kind,
                HumanReviewTask.status.in_(OPEN_STATUSES),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if approval_id is not None:
            # The message's newest draft is the one the inbox shows.
            existing.approval_id = approval_id
        return existing

    target_role, assigned_to = (
        (owner, None)
        if owner is not None
        else await owner_for(db, inbox_task=inbox_task, kind=kind)
    )
    item = HumanReviewTask(
        case_id=inbox_task.case_id,
        task_type=kind,
        status=TaskStatus.PENDING,
        target_role=target_role,
        assigned_to=assigned_to,
        priority=priority or _PRIORITY[inbox_task.priority],
        notes=reason,
        approval_id=approval_id,
        inbox_task_id=inbox_task.id,
        details=details,
    )
    db.add(item)
    await db.flush()
    await record_event(
        db,
        actor=actor,
        case_id=inbox_task.case_id,
        action="review.opened",
        details={
            "review_id": str(item.id),
            "kind": kind.value,
            "target_role": target_role.value,
            "inbox_task_id": str(inbox_task.id),
        },
    )
    return item


async def close_for_approval(
    db: AsyncSession, approval_id: UUID, *, actor: User, approved: bool, notes: str | None
) -> None:
    """Approve or reject, from either screen, closes the linked item (D2)."""
    item = (
        await db.execute(
            select(HumanReviewTask).where(
                HumanReviewTask.approval_id == approval_id,
                HumanReviewTask.status.in_(OPEN_STATUSES),
            )
        )
    ).scalar_one_or_none()
    if item is None:
        return
    item.status = TaskStatus.COMPLETED if approved else TaskStatus.CANCELLED
    await record_event(
        db,
        actor=actor,
        case_id=item.case_id,
        action="review.completed" if approved else "review.dismissed",
        details={"review_id": str(item.id), "kind": item.task_type.value, "note": notes},
    )


async def complete_open(
    db: AsyncSession, *, case_id: UUID, kind: TaskType, actor: User | None, note: str
) -> None:
    """Close a case's open items that something else has settled (e.g. the
    conversation verified the sender). Flushes, never commits."""
    items = await db.scalars(
        select(HumanReviewTask).where(
            HumanReviewTask.case_id == case_id,
            HumanReviewTask.task_type == kind,
            HumanReviewTask.status.in_(OPEN_STATUSES),
        )
    )
    for item in items.all():
        item.status = TaskStatus.COMPLETED
        await record_event(
            db,
            actor=actor,
            case_id=case_id,
            action="review.completed",
            details={"review_id": str(item.id), "kind": kind.value, "note": note},
        )
