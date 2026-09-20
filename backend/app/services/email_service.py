"""Email ingestion pipeline (FR-EMAIL-01/02). Mirrors call_service.route_call's
shape: classify -> resolve target role -> gate -> create the shared Task row.
Draft-reply generation (FR-EMAIL-03) is a separate step (draft_reply()), kept
out of this function so ingestion and drafting can be tested independently.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.llm import get_llm
from app.llm.guardrail import InputBlockedError, guarded_invoke
from app.llm.output_guardrail import OutputBlockedError, check_output
from app.models.case import IntakeCase, IntakeStatus
from app.models.email import Email
from app.models.task import Task, TaskCategory, TaskItemStatus, TaskPriority, TaskSource
from app.models.user import User
from app.schemas.email import EmailIngestRequest
from app.services import approval_service, outlook_auth, outlook_client
from app.services.audit_service import record_event
from app.services.content_classifier import classify_content
from app.services.draft_critic import critique
from app.services.outlook_auth import OutlookAuthRequiredError
from app.services.reply_gate import ReplyGateResult, ReplyWorthiness, evaluate_reply_worthiness
from app.services.task_routing_gate import (
    TaskRoutingGateResult,
    TaskRoutingOutcome,
    evaluate_task_routing_gate,
)
from app.services.task_routing_rules import resolve_target_role

if TYPE_CHECKING:
    from app.rag.retry import Reformulator

logger = logging.getLogger(__name__)


def _clinical_categories() -> frozenset[TaskCategory]:
    """Categories whose replies must be grounded and never auto-send.

    Configurable via settings.email_no_autosend_categories. Unknown values are
    dropped rather than raising, so a bad row degrades to the built-in set.
    """
    values = settings.email_no_autosend_categories
    out = set()
    for v in values:
        try:
            out.add(TaskCategory(v))
        except ValueError:
            continue
    return frozenset(out)


class CaseNotFoundError(Exception):
    """Raised when EmailIngestRequest.case_id is given but doesn't exist."""


class EmailSendError(Exception):
    """Outlook refused a reply. The task is deliberately left draft_sent=False
    so the failure is visible rather than recorded as a delivered message."""


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
        # A polled email carries the mailbox's own receipt time; a directly
        # ingested one has no such timestamp, so fall back to now as before.
        received_at=payload.received_at or datetime.now(UTC),
        external_id=payload.external_id,
        external_source=payload.external_source,
    )
    db.add(email)
    await db.flush()

    llm = get_llm()
    # One text for both readers (spec G.2). The classifier missed an injection
    # in the subject, and the routing gate's URGENT_KEYWORDS scan missed a
    # sender who put "urgent" in the subject line, which is where people put
    # it. Building it once is what stops the two drifting apart again.
    # classify_content itself is unchanged, because the call pipeline shares it
    # and a call has no subject.
    message_text = f"Subject: {payload.subject}\n\n{payload.body}"
    category, confidence = await classify_content(
        db, llm, message_text, actor=actor, channel="email"
    )
    target_role = resolve_target_role(category)
    gate = evaluate_task_routing_gate(category, confidence, message_text)
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


async def _generate_plain_reply(
    db: AsyncSession,
    email: Email,
    actor: User,
    context_text: str = "",
    feedback: str | None = None,
) -> str:
    from app.rag.answer import revision_block

    llm = get_llm()
    context_block = (
        f"CLINIC INFO (use this for hours/policies/contact details, don't invent any):\n"
        f"{context_text}\n\n"
        if context_text
        else ""
    )
    prompt = (
        "You are a clinic administrator replying to a patient email. Write a short, "
        "polite, professional reply. Do not mention any clinical details.\n\n"
        f"{context_block}"
        f"ORIGINAL EMAIL SUBJECT: {email.subject}\n"
        f"ORIGINAL EMAIL BODY: {email.body}\n\n"
        f"{revision_block(feedback)}"
        "REPLY:"
    )
    # The choke point every live LLM call is supposed to use (spec G.2). The
    # prompt embeds the patient's own subject and body, which is exactly the
    # untrusted text the input guardrail exists to catch.
    result = await guarded_invoke(db, llm, prompt, actor=actor, route="email.draft_reply")
    return result if isinstance(result, str) else getattr(result, "content", str(result))


async def _generate_org_grounded_reply(
    db: AsyncSession,
    email: Email,
    actor: User,
    feedback: str | None = None,
    reformulate: "Reformulator | None" = None,
) -> tuple[str, bool]:
    """Non-clinical reply, grounded in the org-wide profile corpus (clinic
    hours, policies) when retrieval clears the same sufficiency_floor gate
    RAG patient queries use. Falls back to the plain ungrounded reply when
    nothing relevant is retrieved.

    Returns (text, grounded) -- grounded is False on the fallback path, so
    draft_reply's auto-send check can tell a fact-grounded reply from a
    generic guess.
    """
    from app.rag.answer import CONTEXT_SCORE_MARGIN
    from app.rag.retrieval import RetrievalContext
    from app.rag.retry import retrieve_gated

    ctx = RetrievalContext(
        patient_id=None, allowed_scopes=["general"], role=actor.role.value, actor=actor.email
    )
    gate_outcome = await retrieve_gated(db, email.body, ctx, reformulate=reformulate)
    if gate_outcome.decision == "manual_handling":
        return await _generate_plain_reply(db, email, actor, feedback=feedback), False

    assert gate_outcome.top_score is not None
    context_chunks = [
        c for c in gate_outcome.chunks if c.score >= gate_outcome.top_score - CONTEXT_SCORE_MARGIN
    ]
    context_text = "\n\n".join(c.content for c in context_chunks)
    text = await _generate_plain_reply(
        db, email, actor, context_text=context_text, feedback=feedback
    )
    return text, True


def approval_payload(
    email_id: str | UUID,
    task_id: str | UUID,
    draft: str | None,
    delivery_error: str | None,
    critic_reason: str | None = None,
) -> dict:
    payload = {"email_id": str(email_id), "task_id": str(task_id), "draft": draft}
    if delivery_error is not None:
        payload["delivery_error"] = delivery_error
    if critic_reason is not None:
        payload["critic_reason"] = critic_reason
    return payload


async def _persist_draft(db: AsyncSession, task: Task, outcome: EmailDraftOutcome) -> None:
    task.draft_text = outcome.draft_text
    task.draft_approval_id = UUID(outcome.approval_id) if outcome.approval_id else None
    task.draft_sent = outcome.sent
    await db.commit()
    await db.refresh(task)


def auto_send_eligible(
    *,
    verdict: ReplyWorthiness,
    gate_outcome: TaskRoutingOutcome,
    confidence: float,
    grounded: bool,
    category: TaskCategory | None,
) -> bool:
    """Whether a draft may go out with no human in the loop.

    The one definition both the flag-off draft_reply and the agent graph call,
    so the two paths can never disagree about what auto-sends.

    With the Outlook connector live, "sent" stops being a DB-level simulation
    and becomes a real message leaving for a real patient inbox, so confidence
    alone is not enough. Every one of these must hold: the LLM judged the email
    worth replying to (not merely UNCERTAIN), the routing gate is fully
    confident (not just flagged), the draft is grounded in retrieved org
    content rather than a generic guess, and the category isn't clinical --
    prescription/results/referral replies never auto-send regardless of
    confidence, per Amin's explicit call.
    """
    return (
        settings.email_auto_send_enabled
        and verdict == ReplyWorthiness.WORTHY
        and gate_outcome == TaskRoutingOutcome.AUTO_ROUTED
        and confidence >= settings.task_routing_auto_threshold
        and grounded
        and category not in _clinical_categories()
    )


# Agent branches whose reply states something the clinic is committing to: a
# time to attend (§10), or what happens to a patient's records (§11). Literal
# names rather than an import, so this module does not import the branches.
_ALWAYS_HUMAN_BRANCHES = frozenset({"booking", "records"})


def reply_risk_tier(
    *,
    revision_count: int,
    grounded_on_retry: bool = False,
    is_provisional: bool = False,
    branch: str | None = None,
) -> str:
    """Whether a draft must reach a human whatever auto_send_eligible says.

    Not the audit log's severity scorer (audit_service._compute_risk_score):
    "how alarming is this log entry" and "must a human approve this reply" are
    different questions. Tiers, not a score (build spec §5 option (a)); later
    branches add rules here rather than new thresholds.
    """
    # A draft the critic had to correct never goes out without a human. The
    # flag-off path already holds a rejected draft for staff; without this the
    # graph's corrected rewrite could auto-send.
    if revision_count > 0:
        return "high"
    # Chunks found by an LLM's rewrite cleared the floor against the rewrite,
    # not against what the patient wrote: weaker evidence. Drafted, never
    # auto-sent (spec §7). Flag off the same email is ungrounded, so it goes
    # to approval there too.
    if grounded_on_retry:
        return "high"
    # A provisional patient is whoever the last email said they were. Their
    # onboarding reply always reaches a human (spec §9.0).
    if is_provisional:
        return "high"
    if branch in _ALWAYS_HUMAN_BRANCHES:
        return "high"
    return "low"


async def deliver_reply(
    db: AsyncSession,
    *,
    email_id: str | UUID | None,
    task_id: str | UUID | None,
    draft: str | None,
    actor: User,
    case_id: UUID | None,
    approval_id: str | UUID | None = None,
) -> None:
    """Send a reply. The only caller of outlook_client.send_reply in the app.

    With the Outlook connector disabled "sent" is DB-level state and no message
    leaves the system. With it enabled the draft is delivered through Graph
    first, and only a successful send sets draft_sent, so a delivery failure
    can never be recorded as a sent reply.

    Raises EmailSendError or OutlookAuthRequiredError, both before anything is
    written, leaving draft_sent False.
    """
    delivered = False

    # Read the delivery record before acting. A retried executor or a resumed
    # graph can land here twice on one approval, and draft_sent is the only
    # thing that knows the patient already got this reply.
    task = await db.get(Task, UUID(str(task_id))) if task_id is not None else None
    if task is not None and task.draft_sent:
        return

    if settings.outlook_enabled and email_id is not None and draft:
        email = await db.get(Email, UUID(str(email_id)))
        if email is not None and email.external_id:
            token = await outlook_auth.get_access_token()
            try:
                await outlook_client.send_reply(token, email.external_id, draft)
            except httpx.HTTPError as exc:
                raise EmailSendError(
                    f"Outlook rejected the reply to message {email.external_id}: {exc}"
                ) from exc
            delivered = True

    # Only reached on a successful send: EmailSendError propagates above, so a
    # failed delivery never records draft_sent.
    if task is not None:
        task.draft_sent = True
        if draft is not None:
            task.draft_text = draft
    await record_event(
        db,
        actor=actor,
        case_id=case_id,
        action="email.sent",
        details={
            "email_id": str(email_id) if email_id is not None else None,
            "approval_id": str(approval_id) if approval_id is not None else None,
            # Distinguishes a real Graph delivery from the simulated path, so
            # the audit log does not claim more than actually happened.
            "delivered": delivered,
        },
    )
    await db.commit()


async def check_reply_worthiness(db: AsyncSession, email: Email, actor: User) -> ReplyGateResult:
    return await evaluate_reply_worthiness(
        db, get_llm(), sender=email.sender, subject=email.subject, body=email.body, actor=actor
    )


async def mark_not_worthy(db: AsyncSession, task: Task, reason: str) -> None:
    """Nothing to reply to: park the task at low priority, saying why."""
    task.priority = TaskPriority.LOW
    task.handover_context = reason
    await _persist_draft(db, task, EmailDraftOutcome(None, None, False, False))


def reformulator(db: AsyncSession, actor: User) -> "Reformulator":
    """The agent graph's retrieval retry, on the same model the draft uses."""
    from app.rag.retry import Reformulator

    return Reformulator(db, actor, get_llm())


async def generate_draft(
    db: AsyncSession,
    task: Task,
    email: Email,
    actor: User,
    feedback: str | None = None,
    reformulate: "Reformulator | None" = None,
) -> tuple[str, bool]:
    """Draft a reply. Returns (text, grounded).

    Clinical categories on a case with a known patient answer from that
    patient's records; everything else is grounded in the org profile corpus.
    feedback is a reviewer's reason for rejecting a previous draft. It goes
    into the generation prompt only, never the retrieval query, so a revision
    is grounded in exactly what the first draft was.
    reformulate is the agent graph's retrieval retry; the flag-off path never
    passes it, so it makes no extra LLM call.
    """
    if task.category in _clinical_categories() and email.case_id is not None:
        case = await db.get(IntakeCase, email.case_id)
        if case is not None and case.patient_id is not None:
            from app.rag.answer import answer_question
            from app.rag.retrieval import RetrievalContext

            # general only (spec G.1). referral_request and medical_records_request
            # route to OPERATOR and admins see every queue, and neither role holds
            # VIEW_CLINICAL by default, so restricted clinical documents must not
            # reach a draft. A draft with nothing general to ground on becomes
            # "not enough information" and staff write it themselves.
            ctx = RetrievalContext(
                patient_id=case.patient_id,
                allowed_scopes=["general"],
                role=actor.role.value,
                actor=actor.email,
            )
            result = await answer_question(
                db, email.body, ctx, actor, feedback=feedback, reformulate=reformulate
            )
            return result.answer, True
    return await _generate_org_grounded_reply(
        db, email, actor, feedback=feedback, reformulate=reformulate
    )


async def persist_draft(
    db: AsyncSession,
    task_id: str | UUID,
    draft_text: str | None,
    approval_id: str | None = None,
    sent: bool = False,
) -> None:
    task = await db.get(Task, UUID(str(task_id)))
    if task is not None:
        await _persist_draft(db, task, EmailDraftOutcome(draft_text, approval_id, sent, False))


async def record_reply_dispatch(
    db: AsyncSession,
    *,
    task_id: str | UUID | None,
    case_id: str | UUID | None,
    actor: User,
    approval_id: str | None,
    delivery_error: str | None,
) -> bool:
    """After an approved reply's executor ran: record what actually happened.

    Reads draft_sent, never sends -- deliver_reply already ran (or failed) in
    the approvals route before this. A failed delivery leaves the task pending
    with the reason in handover_context, since the only recovery is a human
    sending it by hand. Returns whether the reply was sent.
    """
    task = await db.get(Task, UUID(str(task_id))) if task_id is not None else None
    sent = bool(task is not None and task.draft_sent)
    if task is not None and not sent:
        task.handover_context = (
            f"Approved reply was not delivered: {delivery_error or 'unknown error'}. "
            "Send it by hand; re-approving is not possible."
        )
    await record_event(
        db,
        actor=actor,
        case_id=UUID(str(case_id)) if case_id is not None else None,
        action="email.dispatch_recorded",
        details={
            "task_id": str(task_id) if task_id is not None else None,
            "approval_id": approval_id,
            "sent": sent,
            "delivery_error": delivery_error,
        },
    )
    await db.commit()
    return sent


async def record_critic_escalation(
    db: AsyncSession,
    *,
    task_id: str | UUID,
    case_id: str | UUID | None,
    actor: User,
    reason: str,
    drafts: int,
) -> None:
    """Every draft failed the critic: no approval, no send. The Task stays
    pending for a human to answer, with the critic's reason on it."""
    task = await db.get(Task, UUID(str(task_id)))
    if task is not None:
        task.handover_context = (
            f"No reply drafted: {drafts} drafts were rejected by the policy check. {reason}"
        )
    await record_event(
        db,
        actor=actor,
        case_id=UUID(str(case_id)) if case_id is not None else None,
        action="agent.critic_escalated",
        details={"task_id": str(task_id), "reason": reason, "drafts": drafts},
    )
    await db.commit()


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

    The agent graph (app/agents) runs the same steps as nodes, calling the
    same functions; keep the two in step.
    """
    if gate.outcome == TaskRoutingOutcome.HUMAN_REVIEW:
        outcome = EmailDraftOutcome(draft_text=None, approval_id=None, sent=False, blocked=False)
        await _persist_draft(db, task, outcome)
        return outcome

    try:
        reply_verdict = await check_reply_worthiness(db, email, actor)
        if reply_verdict.verdict == ReplyWorthiness.NOT_WORTHY:
            await mark_not_worthy(db, task, reply_verdict.reason)
            return EmailDraftOutcome(draft_text=None, approval_id=None, sent=False, blocked=False)
        draft_text, grounded = await generate_draft(db, task, email, actor)
    except InputBlockedError:
        # Held, not crashed: the Task ingest_email created is the human review
        # item, and it says why. No draft, because the model was never called.
        logger.warning("draft generation blocked by the input guardrail, holding for staff")
        task.handover_context = (
            "No reply drafted: the message was blocked by the prompt injection check. "
            "Read it and reply by hand."
        )
        outcome = EmailDraftOutcome(draft_text=None, approval_id=None, sent=False, blocked=True)
        await _persist_draft(db, task, outcome)
        return outcome
    except Exception:
        # A live LLM/retrieval outage (Ollama timeout, connection drop, etc.)
        # must degrade to "needs a manual reply", not crash the ingest
        # request after the task row is already committed -- an uncaught
        # exception here previously orphaned the task with no draft, no
        # approval, and no visible reason.
        logger.exception("draft generation failed, falling back to manual reply")
        outcome = EmailDraftOutcome(draft_text=None, approval_id=None, sent=False, blocked=False)
        await _persist_draft(db, task, outcome)
        return outcome

    try:
        await check_output(db, draft_text, actor=actor, case_id=email.case_id)
    except OutputBlockedError:
        outcome = EmailDraftOutcome(draft_text=None, approval_id=None, sent=False, blocked=True)
        await _persist_draft(db, task, outcome)
        return outcome

    # The same policy check the agent graph runs, without its regeneration
    # loop: a rejected draft never auto-sends, it goes to staff with the reason
    # and stays editable. The graph instead redrafts up to twice (graph.after_critic).
    critic_reason = critique(draft_text)
    delivery_error = None
    if critic_reason is None and auto_send_eligible(
        verdict=reply_verdict.verdict,
        gate_outcome=gate.outcome,
        confidence=confidence,
        grounded=grounded,
        category=task.category,
    ):
        try:
            await deliver_reply(
                db,
                email_id=email.id,
                task_id=task.id,
                draft=draft_text,
                actor=actor,
                case_id=email.case_id,
            )
        except (EmailSendError, OutlookAuthRequiredError) as exc:
            # A failed auto-send must not vanish: the draft goes to the human
            # queue with the reason, and draft_sent stays False.
            delivery_error = str(exc)
        else:
            outcome = EmailDraftOutcome(
                draft_text=draft_text, approval_id=None, sent=True, blocked=False
            )
            await _persist_draft(db, task, outcome)
            return outcome

    approval = await approval_service.create_approval_request(
        db,
        action_type="email.draft_reply",
        payload=approval_payload(email.id, task.id, draft_text, delivery_error, critic_reason),
        case_id=email.case_id,
        requested_by=actor,
    )
    if critic_reason is not None:
        task.handover_context = f"Held for review by the policy check: {critic_reason}"
    outcome = EmailDraftOutcome(
        draft_text=draft_text, approval_id=str(approval.id), sent=False, blocked=False
    )
    await _persist_draft(db, task, outcome)
    return outcome


def draft_runner():
    """What the ingest paths schedule once ingest_email has committed.

    draft_reply_detached, or with agentic_pipeline_enabled the agent graph,
    which takes the same arguments. Resolved at call time so the flag is
    read per message, and so the flag-off app never imports langgraph.
    """
    if settings.agentic_pipeline_enabled:
        from app.agents import graph

        return graph.start
    return draft_reply_detached


async def draft_reply_detached(
    task_id: UUID,
    email_id: UUID,
    actor_id: UUID,
    gate: TaskRoutingGateResult,
    confidence: float,
) -> None:
    """Run draft_reply in a session of its own.

    Shared by both schedulers -- the ingest route's BackgroundTasks and the
    Outlook poller's detached task -- because both have already returned by
    the time this runs, taking their session with them. Hence ids in, rows
    re-fetched here. Safe because ingest_email() commits before returning.

    Failures are logged and swallowed. There is nobody left to raise to: the
    Email and Task rows are already durable, and an undrafted task simply
    shows up in the inbox as one a human has to answer.
    """
    async with AsyncSessionLocal() as db:
        try:
            task = await db.get(Task, task_id)
            email = await db.get(Email, email_id)
            actor = await db.get(User, actor_id)
            if task is None or email is None or actor is None:
                logger.error("Detached draft for task %s found no task/email/actor row", task_id)
                return
            await draft_reply(db, task, email, actor, gate, confidence)
        except Exception:
            logger.exception("Detached draft reply failed for task %s", task_id)
            await db.rollback()
