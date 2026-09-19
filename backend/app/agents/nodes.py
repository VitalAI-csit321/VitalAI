"""Email reply pipeline nodes (build spec §4).

Each node is an adapter: read state, call the email_service function that
draft_reply calls for the same step, return a partial update. Business rules
live in app/services, so the flag-off path and the graph cannot drift apart.

Every node opens and commits its own session (state.py explains why), and
re-fetches its rows by id, because a row loaded in one node's session is
detached in the next.
"""

from uuid import UUID

from langgraph.runtime import Runtime
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import CaseState, Context
from app.llm.output_guardrail import OutputBlockedError, check_output
from app.models.case import IntakeCase
from app.models.email import Email
from app.models.patient import Patient
from app.models.task import Task
from app.models.user import User
from app.services import consent_service, email_service
from app.services.draft_critic import critique
from app.services.email_service import EmailSendError
from app.services.outlook_auth import OutlookAuthRequiredError
from app.services.reply_gate import ReplyWorthiness


async def _rows(
    db: AsyncSession, state: CaseState, runtime: Runtime[Context]
) -> tuple[Task, Email, User]:
    task = await db.get(Task, UUID(state["task_id"]))
    email = await db.get(Email, UUID(state["source_id"]))
    actor = await db.get(User, runtime.context.actor_id)
    if task is None or email is None or actor is None:
        raise LookupError(f"task/email/actor missing for thread {state['source_id']}")
    return task, email, actor


def _case_id(state: CaseState) -> UUID | None:
    return UUID(state["case_id"]) if state.get("case_id") else None


async def load(state: CaseState, runtime: Runtime[Context]) -> dict:
    """Populate state from the rows ingest_email already committed."""
    async with runtime.context.session_factory() as db:
        task, email, _ = await _rows(db, state, runtime)
        case = await db.get(IntakeCase, email.case_id) if email.case_id else None
        patient = await db.get(Patient, case.patient_id) if case and case.patient_id else None
    return {
        "case_id": str(email.case_id) if email.case_id else None,
        "intent": task.category.value if task.category else None,
        "content": email.body,
        "sender_identifier": email.sender,
        "patient_id": str(patient.id) if patient else None,
        "patient_status": patient.status.value if patient else None,
        "is_provisional": patient.is_provisional if patient else None,
    }


async def consent(state: CaseState, runtime: Runtime[Context]) -> dict:
    """Read-only. Email cases usually have no consent record at all, and that
    must never block a reply (Appendix F.2): this records, it does not gate."""
    case_id = _case_id(state)
    if case_id is None:
        return {"consent_status": "none"}
    async with runtime.context.session_factory() as db:
        record = await consent_service.get_consent_for_case(db, case_id)
    return {"consent_status": record.status.value if record else "none"}


async def reply_gate(state: CaseState, runtime: Runtime[Context]) -> dict:
    async with runtime.context.session_factory() as db:
        task, email, actor = await _rows(db, state, runtime)
        verdict = await email_service.check_reply_worthiness(db, email, actor)
        if verdict.verdict == ReplyWorthiness.NOT_WORTHY:
            await email_service.mark_not_worthy(db, task, verdict.reason)
            return {"reply_verdict": verdict.verdict.value, "dispatch_result": "not_worthy"}
    return {"reply_verdict": verdict.verdict.value}


async def draft(state: CaseState, runtime: Runtime[Context]) -> dict:
    """First draft, or a regeneration after the critic rejected the last one.
    A regeneration carries the critic's reason into the prompt and counts
    toward revision_count, which the edge after critic caps."""
    revising = state.get("critic_verdict") == "reject"
    async with runtime.context.session_factory() as db:
        task, email, actor = await _rows(db, state, runtime)
        text, grounded = await email_service.generate_draft(
            db, task, email, actor, feedback=state.get("critic_reason") if revising else None
        )
    update: dict = {"draft_text": text, "grounded": grounded}
    if revising:
        update["revision_count"] = state.get("revision_count", 0) + 1
    return update


async def critic(state: CaseState) -> dict:
    reason = critique(state.get("draft_text"))
    return {"critic_verdict": "reject" if reason else "pass", "critic_reason": reason}


async def escalate(state: CaseState, runtime: Runtime[Context]) -> dict:
    async with runtime.context.session_factory() as db:
        actor = await db.get(User, runtime.context.actor_id)
        await email_service.record_critic_escalation(
            db,
            task_id=state["task_id"],
            case_id=state.get("case_id"),
            actor=actor,
            reason=state["critic_reason"],
            drafts=state.get("revision_count", 0) + 1,
        )
    return {"dispatch_result": "escalated"}


async def guardrail(state: CaseState, runtime: Runtime[Context]) -> dict:
    async with runtime.context.session_factory() as db:
        actor = await db.get(User, runtime.context.actor_id)
        try:
            await check_output(db, state["draft_text"], actor=actor, case_id=_case_id(state))
        except OutputBlockedError:
            await email_service.persist_draft(db, state["task_id"], None)
            return {"dispatch_result": "blocked"}
    return {}


async def risk(state: CaseState) -> dict:
    """§5.1: HIGH sends the draft to approval whatever the auto-send predicate says."""
    return {
        "risk_tier": email_service.reply_risk_tier(revision_count=state.get("revision_count", 0))
    }


async def auto_send(state: CaseState, runtime: Runtime[Context]) -> dict:
    """Deliver through the one shared send path. A failed delivery routes to
    create_approval with the reason, so the draft reaches the human queue."""
    async with runtime.context.session_factory() as db:
        actor = await db.get(User, runtime.context.actor_id)
        try:
            await email_service.deliver_reply(
                db,
                email_id=state["source_id"],
                task_id=state["task_id"],
                draft=state["draft_text"],
                actor=actor,
                case_id=_case_id(state),
            )
        except (EmailSendError, OutlookAuthRequiredError) as exc:
            return {"delivery_error": str(exc)}
    return {"dispatch_result": "sent", "delivery_error": None}


async def dispatch(state: CaseState, runtime: Runtime[Context]) -> dict:
    """Never sends. The approvals route's executor already ran deliver_reply
    before scheduling this resume; this reads the result and records it."""
    async with runtime.context.session_factory() as db:
        actor = await db.get(User, runtime.context.actor_id)
        sent = await email_service.record_reply_dispatch(
            db,
            task_id=state.get("task_id"),
            case_id=state.get("case_id"),
            actor=actor,
            approval_id=state.get("approval_request_id"),
            delivery_error=state.get("delivery_error"),
        )
    return {"dispatch_result": "sent" if sent else "send_failed"}
