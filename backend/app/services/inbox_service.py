"""Unified, RBAC-scoped inbox feed (both channels). Task.target_role is
populated identically by the email pipeline and the unified call pipeline,
so one filter works for both -- the entire point of unifying both channels
under one classifier and gate.
"""

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from langchain_core.language_models import BaseLanguageModel
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import VIEW_ALL_QUEUES, effective_permissions
from app.auth.scoping import assigned_patient_ids_subquery
from app.config import settings
from app.llm import get_llm
from app.llm.guardrail import InputBlockedError, guarded_invoke
from app.models.assignment import DoctorPatientAssignment
from app.models.call import Call
from app.models.case import IntakeCase
from app.models.email import Email
from app.models.task import Task, TaskItemStatus, TaskPriority, TaskSource
from app.models.user import User, UserRole
from app.schemas.inbox import InboxMessageOut

logger = logging.getLogger(__name__)

_PRIORITY_MAP: dict[TaskPriority, str] = {
    TaskPriority.URGENT: "urgent",
    TaskPriority.HIGH: "urgent",
    TaskPriority.MEDIUM: "normal",
    TaskPriority.LOW: "fyi",
}


def _initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _received_label(dt: datetime) -> str:
    # Stored instants are UTC; staff read clinic time, like the calendar does.
    local = (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(
        ZoneInfo(settings.clinic_timezone)
    )
    return local.strftime("%d %b %Y, %H:%M")


BLOCKED_SUMMARY = "Summary unavailable. Open the call to read the transcript."


async def summarize_call(
    db: AsyncSession, llm: BaseLanguageModel, transcript: str, actor: User
) -> str:
    """One inbox preview line. Through the choke point (spec G.2): a call
    transcript is untrusted external text, same as an email body.

    A block shows a fixed placeholder rather than raising, so one hostile
    transcript cannot take down the whole inbox listing.
    """
    prompt = (
        "Summarize this phone call transcript in one short sentence, for a staff "
        "inbox preview. No preamble, just the sentence.\n\n"
        f"TRANSCRIPT:\n{transcript}\n\nSUMMARY:"
    )
    try:
        result = await guarded_invoke(db, llm, prompt, actor=actor, route="call.summarize")
    except InputBlockedError:
        logger.warning("summarize_call: guardrail blocked a transcript, showing a placeholder")
        return BLOCKED_SUMMARY
    return result if isinstance(result, str) else getattr(result, "content", str(result))


async def _visible_tasks(db: AsyncSession, actor: User, archived: bool = False) -> list[Task]:
    status_filter = (
        Task.status == TaskItemStatus.COMPLETED
        if archived
        else Task.status != TaskItemStatus.COMPLETED
    )
    query = select(Task).where(status_filter, Task.deleted_at.is_(None))
    if VIEW_ALL_QUEUES not in effective_permissions(actor):
        in_queue = Task.target_role == actor.role
        if actor.role == UserRole.OPERATOR:
            # Doctors see doctor work only for patients assigned to them, so a
            # results or referral email for a patient with no doctor (or no
            # identified patient) was visible to nobody but an admin.
            has_doctor = (
                select(IntakeCase.id)
                .join(
                    DoctorPatientAssignment,
                    DoctorPatientAssignment.patient_id == IntakeCase.patient_id,
                )
                .where(IntakeCase.id == Task.case_id)
                .exists()
            )
            in_queue = or_(in_queue, and_(Task.target_role == UserRole.DOCTOR, ~has_doctor))
        query = query.where(in_queue)
    if actor.role == UserRole.DOCTOR:
        query = query.join(IntakeCase, Task.case_id == IntakeCase.id).where(
            IntakeCase.patient_id.in_(assigned_patient_ids_subquery(actor.id))
        )
    query = query.order_by(Task.created_at.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


async def _to_message(db: AsyncSession, task: Task, actor: User) -> InboxMessageOut | None:
    priority = _PRIORITY_MAP[task.priority]
    unread = task.read_at is None
    category = task.category.value if task.category else "uncategorized"

    if task.source == TaskSource.EMAIL:
        result = await db.execute(select(Email).where(Email.case_id == task.case_id))
        email = result.scalars().first()
        if email is None:
            return None
        return InboxMessageOut(
            id=str(task.id),
            caseId=str(task.case_id),
            fromName=email.sender,
            fromInitials=_initials(email.sender.split("@")[0].replace(".", " ")),
            toName=email.recipient,
            subject=email.subject,
            body=email.body,
            priority=priority,
            category=category,
            unread=unread,
            receivedLabel=_received_label(email.received_at),
            threadReference=f"EMAIL-{task.id}",
            avatarColor="#2563eb",
            draftText=task.draft_text,
            draftApprovalId=str(task.draft_approval_id) if task.draft_approval_id else None,
            draftSent=task.draft_sent,
            taskStatus=task.status.value,
            emailId=str(email.id),
            handoverContext=task.handover_context,
        )

    call_result = await db.execute(select(Call).where(Call.id == task.call_id))
    call = call_result.scalars().first()
    if call is None:
        return None
    return InboxMessageOut(
        id=str(task.id),
        caseId=str(task.case_id),
        fromName=call.phone_number,
        fromInitials="CL",
        toName="Clinic",
        subject=f"Call from {call.phone_number}",
        body=(
            await summarize_call(db, get_llm(), call.transcript, actor) if call.transcript else ""
        ),
        priority=priority,
        category=category,
        unread=unread,
        receivedLabel=_received_label(task.created_at),
        threadReference=f"CALL-{task.id}",
        avatarColor="#059669",
        taskStatus=task.status.value,
        handoverContext=task.handover_context,
        callId=str(call.id),
        hasAudio=call.audio_key is not None,
    )


async def list_inbox(
    db: AsyncSession, actor: User, limit: int = 50, offset: int = 0, archived: bool = False
) -> tuple[list[InboxMessageOut], int]:
    tasks = await _visible_tasks(db, actor, archived=archived)
    total = len(tasks)
    page = tasks[offset : offset + limit]

    items: list[InboxMessageOut] = []
    for task in page:
        message = await _to_message(db, task, actor)
        if message is not None:
            items.append(message)
    return items, total
