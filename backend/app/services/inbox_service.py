"""Unified, RBAC-scoped inbox feed (both channels). Task.target_role is
populated identically by the email pipeline and the unified call pipeline,
so one filter works for both -- the entire point of unifying both channels
under one classifier and gate.
"""

from datetime import datetime

from langchain_core.language_models import BaseLanguageModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import VIEW_ALL_QUEUES, effective_permissions
from app.auth.scoping import assigned_patient_ids_subquery
from app.llm import get_llm
from app.models.call import Call
from app.models.case import IntakeCase
from app.models.email import Email
from app.models.task import Task, TaskItemStatus, TaskPriority, TaskSource
from app.models.user import User, UserRole
from app.schemas.inbox import InboxMessageOut

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
    return dt.strftime("%d %b %Y, %H:%M")


async def summarize_call(llm: BaseLanguageModel, transcript: str) -> str:
    prompt = (
        "Summarize this phone call transcript in one short sentence, for a staff "
        "inbox preview. No preamble, just the sentence.\n\n"
        f"TRANSCRIPT:\n{transcript}\n\nSUMMARY:"
    )
    result = await llm.ainvoke(prompt)
    return result if isinstance(result, str) else getattr(result, "content", str(result))


async def _visible_tasks(db: AsyncSession, actor: User, archived: bool = False) -> list[Task]:
    status_filter = (
        Task.status == TaskItemStatus.COMPLETED
        if archived
        else Task.status != TaskItemStatus.COMPLETED
    )
    query = select(Task).where(status_filter, Task.deleted_at.is_(None))
    if VIEW_ALL_QUEUES not in effective_permissions(actor):
        query = query.where(Task.target_role == actor.role)
    if actor.role == UserRole.DOCTOR:
        query = query.join(IntakeCase, Task.case_id == IntakeCase.id).where(
            IntakeCase.patient_id.in_(assigned_patient_ids_subquery(actor.id))
        )
    query = query.order_by(Task.created_at.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


async def _to_message(db: AsyncSession, task: Task) -> InboxMessageOut | None:
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
        fromName=call.phone_number,
        fromInitials="CL",
        toName="Clinic",
        subject=f"Call from {call.phone_number}",
        body=await summarize_call(get_llm(), call.transcript) if call.transcript else "",
        priority=priority,
        category=category,
        unread=unread,
        receivedLabel=_received_label(task.created_at),
        threadReference=f"CALL-{task.id}",
        avatarColor="#059669",
        taskStatus=task.status.value,
    )


async def list_inbox(
    db: AsyncSession, actor: User, limit: int = 50, offset: int = 0, archived: bool = False
) -> tuple[list[InboxMessageOut], int]:
    tasks = await _visible_tasks(db, actor, archived=archived)
    total = len(tasks)
    page = tasks[offset : offset + limit]

    items: list[InboxMessageOut] = []
    for task in page:
        message = await _to_message(db, task)
        if message is not None:
            items.append(message)
    return items, total
