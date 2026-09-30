"""Unified, RBAC-scoped inbox feed (both channels). Task.target_role is
populated identically by the email pipeline and the unified call pipeline,
so one filter works for both -- the entire point of unifying both channels
under one classifier and gate.
"""

import logging
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from langchain_core.language_models import BaseLanguageModel
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import MANAGE_CASES, VIEW_ALL_QUEUES, effective_permissions
from app.auth.scoping import assigned_patient_ids_subquery
from app.config import settings
from app.llm import get_llm
from app.llm.guardrail import InputBlockedError, guarded_invoke
from app.models.approval import ApprovalStatus
from app.models.assignment import DoctorPatientAssignment
from app.models.call import Call
from app.models.case import IntakeCase
from app.models.email import Email
from app.models.episode import Episode, EpisodeStatus
from app.models.human_review import HumanReviewTask, TaskStatus, TaskType
from app.models.task import Task, TaskItemStatus, TaskPriority, TaskSource
from app.models.user import User, UserRole
from app.schemas.inbox import InboxMessageOut
from app.services import approval_service, email_service, human_review_service, review_routing

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


def _scoped(query, actor: User):
    """The role scoping _visible_tasks applies, reusable for one message too."""
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
        # A message in a case is its case doctor's while they are active and
        # still assigned to the patient; otherwise every assigned doctor's, as
        # before cases (booking_service.doctor_for_contact is the same rule).
        case_doctor_holds = (
            select(DoctorPatientAssignment.doctor_id)
            .join(User, User.id == DoctorPatientAssignment.doctor_id)
            .where(
                DoctorPatientAssignment.patient_id == IntakeCase.patient_id,
                DoctorPatientAssignment.doctor_id == Episode.doctor_id,
                User.is_active.is_(True),
            )
            .exists()
        )
        query = (
            query.join(IntakeCase, Task.case_id == IntakeCase.id)
            .outerjoin(Episode, IntakeCase.episode_id == Episode.id)
            .where(
                IntakeCase.patient_id.in_(assigned_patient_ids_subquery(actor.id)),
                or_(Episode.doctor_id == actor.id, ~case_doctor_holds),
            )
        )
    return query


async def can_act_on_task(db: AsyncSession, actor: User, task: Task) -> bool:
    """Spec section 7 on the message itself, so it holds with no review item
    too: what the actor's own inbox shows (the admin sees everything), plus
    the front desk's messages for the operator (D6)."""
    if actor.role == UserRole.OPERATOR and task.target_role == UserRole.FRONT_DESK:
        return True
    return await db.scalar(_scoped(select(Task.id).where(Task.id == task.id), actor)) is not None


async def write_reply_open(db: AsyncSession, task: Task) -> bool:
    """Write reply (D14): an email nothing was sent on, with no AI draft
    awaiting approval. Covers no draft, a blocked one, a rejected one, and an
    approved one whose delivery failed."""
    # Archived (completed) messages were usually answered outside the system.
    if (
        task.source != TaskSource.EMAIL
        or task.draft_sent
        or task.status == TaskItemStatus.COMPLETED
    ):
        return False
    if task.draft_approval_id is None:
        return True
    approval = await approval_service.get_approval(db, task.draft_approval_id)
    return approval is None or approval.status != ApprovalStatus.PENDING


async def _visible_tasks(db: AsyncSession, actor: User, archived: bool = False) -> list[Task]:
    status_filter = (
        Task.status == TaskItemStatus.COMPLETED
        if archived
        else Task.status != TaskItemStatus.COMPLETED
    )
    query = _scoped(select(Task).where(status_filter, Task.deleted_at.is_(None)), actor)
    query = query.order_by(Task.created_at.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


async def _email_for(db: AsyncSession, task: Task) -> Email | None:
    result = await db.execute(select(Email).where(Email.case_id == task.case_id))
    return result.scalars().first()


async def _to_message(db: AsyncSession, task: Task, actor: User) -> InboxMessageOut | None:
    priority = _PRIORITY_MAP[task.priority]
    unread = task.read_at is None
    category = task.category.value if task.category else "uncategorized"

    if task.source == TaskSource.EMAIL:
        email = await _email_for(db, task)
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


async def _case_chip(db: AsyncSession, task: Task) -> dict:
    """Who the message is from (once confirmed) and the case it is in (M4)."""
    contact = await db.get(IntakeCase, task.case_id)
    episode = await db.get(Episode, contact.episode_id) if contact and contact.episode_id else None
    return {
        "patientId": str(contact.patient_id) if contact and contact.patient_id else None,
        "episodeId": str(episode.id) if episode else None,
        # A reply on a closed case's conversation lands there: say so, so
        # staff reopen it or file the message under another case.
        "episodeTitle": (
            f"{episode.title} (closed)" if episode.status == EpisodeStatus.CLOSED else episode.title
        )
        if episode
        else None,
    }


async def _with_review(
    db: AsyncSession, actor: User, task: Task, message: InboxMessageOut
) -> InboxMessageOut:
    """canApprove and reviewItemId: server-decided, never inferred by the UI
    from the actor's role (review queue spec section 7). Also the case chip."""
    item = (
        await db.execute(
            select(HumanReviewTask)
            .where(
                HumanReviewTask.inbox_task_id == task.id,
                HumanReviewTask.status.in_(review_routing.OPEN_STATUSES),
            )
            .order_by(HumanReviewTask.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    # The UI offers Reject/links off this id, so it must never point at an
    # item the viewer cannot act on.
    review_item_id = (
        str(item.id) if item and await human_review_service.can_act(db, actor, item) else None
    )

    # A draft only counts as pending while its ApprovalRequest is still
    # PENDING: a reject, or an approve whose delivery failed, leaves
    # draft_approval_id/draft_sent unchanged, so those alone are not enough
    # (a rejected or already-decided draft must not still offer Approve).
    approval = (
        await approval_service.get_approval(db, task.draft_approval_id)
        if task.draft_approval_id is not None
        else None
    )
    if approval is None or approval.status != ApprovalStatus.PENDING or task.draft_sent:
        can = False
    else:
        draft_item = await human_review_service.item_for_approval(db, approval.id)
        can = (
            await human_review_service.can_approve(db, actor, draft_item)
            if draft_item is not None
            else MANAGE_CASES in effective_permissions(actor)
        )
    can_write = await write_reply_open(db, task) and await can_act_on_task(db, actor, task)
    return message.model_copy(
        update={
            "canApprove": can,
            "reviewItemId": review_item_id,
            "canWriteReply": can_write,
            **await _case_chip(db, task),
        }
    )


async def openable_task(db: AsyncSession, actor: User, task_id: UUID) -> Task | None:
    """The inbox's own message, or one a review item links the actor to
    (e.g. an operator opening a front desk item via D6, or a doctor a
    reassigned draft)."""
    task = await db.get(Task, task_id)
    if task is None or task.deleted_at is not None:
        return None
    visible = await db.scalar(_scoped(select(Task.id).where(Task.id == task_id), actor))
    if visible is None:
        # Only a currently open item can grant access: once an item is
        # completed/cancelled it is no longer live authority over the
        # message, or the actor would keep permanent read access to a
        # message that has since left its scope (e.g. after it is
        # re-routed away or its identity item is linked).
        items = (
            (
                await db.execute(
                    select(HumanReviewTask).where(
                        HumanReviewTask.inbox_task_id == task_id,
                        HumanReviewTask.status.in_(review_routing.OPEN_STATUSES),
                    )
                )
            )
            .scalars()
            .all()
        )
        can_act_any = False
        for item in items:
            if await human_review_service.can_act(db, actor, item):
                can_act_any = True
                break
        if not can_act_any:
            return None
    return task


async def get_message(db: AsyncSession, actor: User, task_id: UUID) -> InboxMessageOut | None:
    task = await openable_task(db, actor, task_id)
    if task is None:
        return None
    message = await _to_message(db, task, actor)
    return await _with_review(db, actor, task, message) if message is not None else None


class WriteReplyClosedError(Exception):
    """Write reply is not offered on this message (not an email, already
    answered, or an AI draft awaits approval)."""


# What a reply answers. A routing, identity or intent question is still open
# after a reply, and a held draft closes through approve/reject.
_ANSWERED_BY_A_REPLY = (TaskType.AGENT_FAILURE, TaskType.AGENT_HANDOVER, TaskType.COMPLAINT_REVIEW)


async def write_reply(db: AsyncSession, actor: User, task: Task, text: str) -> InboxMessageOut:
    """Send a person's own reply (D14) through deliver_reply, the only send
    path: no approval and no critic, a person wrote it. The linked items it
    answers close in the same commit. The caller checks can_act_on_task.

    Raises WriteReplyClosedError, or deliver_reply's EmailSendError /
    OutlookAuthRequiredError after rolling back, so nothing is committed.
    """
    # Row lock: two sends racing past the draft_sent check would both mail the patient.
    await db.refresh(task, with_for_update=True)
    email = await _email_for(db, task)
    if email is None or not await write_reply_open(db, task):
        raise WriteReplyClosedError("This message cannot be answered with a written reply")

    items = await db.scalars(
        select(HumanReviewTask).where(
            HumanReviewTask.inbox_task_id == task.id,
            HumanReviewTask.status.in_(review_routing.OPEN_STATUSES),
            HumanReviewTask.task_type.in_(_ANSWERED_BY_A_REPLY),
        )
    )
    for item in items.all():
        item.status = TaskStatus.COMPLETED
        await human_review_service._audit(
            db, actor, item, "review.completed", note="Replied by hand"
        )

    try:
        await email_service.deliver_reply(
            db,
            email_id=email.id,
            task_id=task.id,
            draft=text,
            actor=actor,
            case_id=task.case_id,
            manual=True,
        )
    except Exception:
        await db.rollback()  # nothing was sent, so the items stay open
        raise
    message = await _to_message(db, task, actor)
    assert message is not None  # an email task with its email, checked above
    return await _with_review(db, actor, task, message)


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
            items.append(await _with_review(db, actor, task, message))
    return items, total
