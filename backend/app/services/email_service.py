"""Email ingestion pipeline (FR-EMAIL-01/02). Mirrors call_service.route_call's
shape: classify -> resolve target role -> gate -> create the shared Task row.
Draft-reply generation (FR-EMAIL-03) is a separate step (draft_reply()), kept
out of this function so ingestion and drafting can be tested independently.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.llm import get_llm
from app.llm.output_guardrail import OutputBlockedError, check_output
from app.models.case import IntakeCase, IntakeStatus
from app.models.email import Email
from app.models.task import Task, TaskCategory, TaskItemStatus, TaskPriority, TaskSource
from app.models.user import User
from app.schemas.email import EmailIngestRequest
from app.services import approval_service
from app.services.audit_service import record_event
from app.services.content_classifier import classify_content
from app.services.task_routing_gate import (
    TaskRoutingGateResult,
    TaskRoutingOutcome,
    evaluate_task_routing_gate,
)
from app.services.task_routing_rules import resolve_target_role

_CLINICAL_CATEGORIES = frozenset(
    {TaskCategory.PRESCRIPTION_RENEWAL, TaskCategory.RESULTS_ENQUIRY, TaskCategory.REFERRAL_REQUEST}
)


class CaseNotFoundError(Exception):
    """Raised when EmailIngestRequest.case_id is given but doesn't exist."""


def _priority_for_gate(gate: TaskRoutingGateResult) -> TaskPriority:
    if gate.outcome == TaskRoutingOutcome.HUMAN_REVIEW:
        return TaskPriority.URGENT if gate.override_reason else TaskPriority.HIGH
    if gate.outcome == TaskRoutingOutcome.AUTO_ROUTED_FLAGGED:
        return TaskPriority.MEDIUM
    return TaskPriority.LOW


async def ingest_email(
    db: AsyncSession, payload: EmailIngestRequest, actor: User
) -> tuple[Email, Task, TaskRoutingGateResult, float]:
    if payload.case_id is not None:
        case = await db.get(IntakeCase, payload.case_id)
        if case is None:
            raise CaseNotFoundError(f"Case {payload.case_id} not found")
    else:
        case = IntakeCase(
            contact_reason=payload.subject,
            contact_channel="email",
            status=IntakeStatus.RECEIVED,
        )
        db.add(case)
        await db.flush()

    email = Email(
        case_id=case.id,
        sender=payload.sender,
        recipient=payload.recipient,
        subject=payload.subject,
        body=payload.body,
        received_at=datetime.now(UTC),
    )
    db.add(email)
    await db.flush()

    llm = get_llm()
    category, confidence = await classify_content(
        db, llm, payload.body, actor=actor, channel="email"
    )
    target_role = resolve_target_role(category)
    gate = evaluate_task_routing_gate(category, confidence, payload.body)
    priority = _priority_for_gate(gate)

    task = Task(
        case_id=case.id,
        source=TaskSource.EMAIL,
        category=category,
        target_role=target_role,
        priority=priority,
        status=TaskItemStatus.PENDING,
    )
    db.add(task)
    await db.flush()

    await record_event(
        db,
        case_id=case.id,
        actor=actor,
        action="email.received",
        details={
            "email_id": str(email.id),
            "task_id": str(task.id),
            "category": category.value,
            "confidence": confidence,
            "target_role": target_role.value,
            "outcome": gate.outcome.value,
            "override_reason": gate.override_reason,
        },
    )
    await db.commit()
    await db.refresh(email)
    await db.refresh(task)
    return email, task, gate, confidence


@dataclass
class EmailDraftOutcome:
    draft_text: str | None
    approval_id: str | None
    sent: bool
    blocked: bool


async def _generate_plain_reply(email: Email, actor: User) -> str:
    llm = get_llm()
    prompt = (
        "You are a clinic administrator replying to a patient email. Write a short, "
        "polite, professional reply. Do not mention any clinical details.\n\n"
        f"ORIGINAL EMAIL SUBJECT: {email.subject}\n"
        f"ORIGINAL EMAIL BODY: {email.body}\n\n"
        "REPLY:"
    )
    result = await llm.ainvoke(prompt)
    return result if isinstance(result, str) else getattr(result, "content", str(result))


async def _persist_draft(db: AsyncSession, task: Task, outcome: EmailDraftOutcome) -> None:
    task.draft_text = outcome.draft_text
    task.draft_approval_id = UUID(outcome.approval_id) if outcome.approval_id else None
    task.draft_sent = outcome.sent
    await db.commit()
    await db.refresh(task)


async def draft_reply(
    db: AsyncSession,
    task: Task,
    email: Email,
    actor: User,
    gate: TaskRoutingGateResult,
    confidence: float,
) -> EmailDraftOutcome:
    """Generate and gate a reply for an auto-routed email. No draft is
    attempted for a human_review outcome -- that email already sits in the
    queue as-is, per the spec. Whatever outcome results is persisted onto
    the task row (draft_text/draft_approval_id/draft_sent) so it survives
    past this one request and can be surfaced later by the inbox.
    """
    if gate.outcome == TaskRoutingOutcome.HUMAN_REVIEW:
        outcome = EmailDraftOutcome(draft_text=None, approval_id=None, sent=False, blocked=False)
        await _persist_draft(db, task, outcome)
        return outcome

    if task.category in _CLINICAL_CATEGORIES and email.case_id is not None:
        case = await db.get(IntakeCase, email.case_id)
        if case is not None and case.patient_id is not None:
            from app.rag.answer import answer_question
            from app.rag.retrieval import RetrievalContext

            ctx = RetrievalContext(
                patient_id=case.patient_id,
                allowed_scopes=["general", "restricted"],
                role=actor.role.value,
                actor=actor.email,
            )
            result = await answer_question(db, email.body, ctx, actor)
            draft_text = result.answer
        else:
            draft_text = await _generate_plain_reply(email, actor)
    else:
        draft_text = await _generate_plain_reply(email, actor)

    try:
        await check_output(db, draft_text, actor=actor, case_id=email.case_id)
    except OutputBlockedError:
        outcome = EmailDraftOutcome(draft_text=None, approval_id=None, sent=False, blocked=True)
        await _persist_draft(db, task, outcome)
        return outcome

    safe_to_send_immediately = (
        gate.outcome == TaskRoutingOutcome.AUTO_ROUTED
        and confidence >= settings.task_routing_auto_threshold
    )
    if safe_to_send_immediately:
        outcome = EmailDraftOutcome(
            draft_text=draft_text, approval_id=None, sent=True, blocked=False
        )
        await _persist_draft(db, task, outcome)
        return outcome

    approval = await approval_service.create_approval_request(
        db,
        action_type="email.draft_reply",
        payload={"email_id": str(email.id), "task_id": str(task.id), "draft": draft_text},
        case_id=email.case_id,
        requested_by=actor,
    )
    outcome = EmailDraftOutcome(
        draft_text=draft_text, approval_id=str(approval.id), sent=False, blocked=False
    )
    await _persist_draft(db, task, outcome)
    return outcome
