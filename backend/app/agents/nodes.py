"""Email reply pipeline nodes (build spec §4).

Each node is an adapter: read state, call the email_service function that
draft_reply calls for the same step, return a partial update. Business rules
live in app/services, so the flag-off path and the graph cannot drift apart.

Every node opens and commits its own session (state.py explains why), and
re-fetches its rows by id, because a row loaded in one node's session is
detached in the next.
"""

from datetime import date
from uuid import UUID

from langgraph.runtime import Runtime
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import CaseState, Context
from app.llm.output_guardrail import OutputBlockedError, check_output
from app.models.case import IntakeCase
from app.models.email import Email
from app.models.patient import Patient
from app.models.task import Task, TaskCategory
from app.models.user import User
from app.services import (
    booking_service,
    consent_service,
    email_service,
    identity_service,
    onboarding_service,
    prescription_service,
    records_service,
    task_service,
)
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


def _patient_id(state: CaseState) -> UUID | None:
    return UUID(state["patient_id"]) if state.get("patient_id") else None


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
        "patient_name": patient.name if patient else None,
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


async def identity(state: CaseState, runtime: Runtime[Context]) -> dict:
    """Who sent this (§8). Recorded for every case; route_identity decides
    whether the outcome blocks. A general intent makes no LLM call."""
    async with runtime.context.session_factory() as db:
        _, email, actor = await _rows(db, state, runtime)
        result, fields = await identity_service.identify_sender(
            db,
            # The model every email step uses, so one fake covers them all.
            llm=email_service.get_llm(),
            intent=TaskCategory(state["intent"]) if state.get("intent") else None,
            case_id=_case_id(state),
            sender=email.sender,
            content=email.body,
            actor=actor,
        )
    update: dict = {
        "identity_outcome": result.outcome.value,
        "identity_fields": {
            "name": fields.name,
            "dob": fields.dob.isoformat() if fields.dob else None,
            "phone": fields.phone,
        },
    }
    if result.patient is not None:
        update |= {
            "patient_id": str(result.patient.id),
            "patient_name": result.patient.name,
            "patient_status": result.patient.status.value,
            "is_provisional": result.patient.is_provisional,
        }
    return update


async def onboarding(state: CaseState, runtime: Runtime[Context]) -> dict:
    """A stranger asking to join or to book (§9.0): create the provisional
    patient and record their implied consent, once. The reply itself is
    drafted by the draft node, so a critic redraft does not repeat this."""
    fields = state.get("identity_fields") or {}
    async with runtime.context.session_factory() as db:
        _, email, actor = await _rows(db, state, runtime)
        patient = await onboarding_service.start_onboarding(
            db,
            case_id=_case_id(state),
            sender=email.sender,
            fields=identity_service.IdentityFields(
                name=fields.get("name"),
                dob=date.fromisoformat(fields["dob"]) if fields.get("dob") else None,
                phone=fields.get("phone"),
            ),
            actor=actor,
        )
        if patient is None:
            # No name means no patient row (Patient.name is NOT NULL).
            await identity_service.hold_for_staff(
                db, state["task_id"], identity_service.IdentityOutcome.NO_MATCH
            )
            return {"dispatch_result": "identity_hold"}
        requested = onboarding_service.fields_to_request(patient)
    return {
        "branch": onboarding_service.BRANCH,
        "requested_fields": requested,
        "patient_id": str(patient.id),
        "patient_status": patient.status.value,
        "is_provisional": True,
    }


async def booking(state: CaseState, runtime: Runtime[Context]) -> dict:
    """§10: the patient's own doctor, and the next free times in their diary.

    Proposes and stops. Nothing here books: book_appointment keeps exactly one
    caller in the app and it is not this one. Either half missing is a hold for
    a human with the reason on the Task, not an email that proposes nothing.
    """
    async with runtime.context.session_factory() as db:
        _, _, actor = await _rows(db, state, runtime)
        assigned = await booking_service.doctor_for_patient(db, UUID(state["patient_id"]))
        if assigned is None:
            await task_service.hold_for_staff(
                db, state["task_id"], booking_service.NO_DOCTOR_REASON
            )
            return {"dispatch_result": "booking_hold"}
        doctor_id, doctor_name = assigned
        slots = await booking_service.find_slots(db, actor, doctor_id)
        if not slots:
            await task_service.hold_for_staff(db, state["task_id"], booking_service.NO_SLOTS_REASON)
            return {"dispatch_result": "booking_hold"}
    return {
        "branch": booking_service.BRANCH,
        "proposed_slots": [slot.isoformat() for slot in slots],
        "booking_doctor_name": doctor_name,
    }


async def records(state: CaseState, runtime: Runtime[Context]) -> dict:
    """§11: consent decides which acknowledgement is drafted, and nothing else.

    No retrieval: no clinical content of any kind reaches a generated email.
    """
    async with runtime.context.session_factory() as db:
        on_file = await records_service.has_explicit_consent(db, _patient_id(state))
    return {"branch": records_service.BRANCH, "records_consent": on_file}


async def prescription(state: CaseState, runtime: Runtime[Context]) -> dict:
    """§12: read the history, raise an internal request, acknowledge.

    Returns `branch`, which is what makes reply_risk_tier see this as an
    always-human branch. A node that forgot it would let a prescription reply
    take the ordinary low risk path.

    The history is read through medication_service, which enforces
    VIEW_CLINICAL itself; the agent actor holds it only by an explicit grant.
    No clinical detail reaches the draft: the branch chooses between two
    fixed acknowledgements and nothing else.
    """
    async with runtime.context.session_factory() as db:
        _, _, actor = await _rows(db, state, runtime)
        review_due = await prescription_service.handle_renewal(
            db,
            case_id=UUID(state["case_id"]),
            patient_id=_patient_id(state),
            actor=actor,
        )
    return {"branch": prescription_service.BRANCH, "prescription_review_due": review_due}


async def identity_hold(state: CaseState, runtime: Runtime[Context]) -> dict:
    async with runtime.context.session_factory() as db:
        await identity_service.hold_for_staff(
            db, state["task_id"], identity_service.IdentityOutcome(state["identity_outcome"])
        )
    return {"dispatch_result": "identity_hold"}


async def draft(state: CaseState, runtime: Runtime[Context]) -> dict:
    """First draft, or a regeneration after the critic rejected the last one.
    A regeneration carries the critic's reason into the prompt and counts
    toward revision_count, which the edge after critic caps."""
    revising = state.get("critic_verdict") == "reject"
    feedback = state.get("critic_reason") if revising else None
    branch = state.get("branch")
    if branch == onboarding_service.BRANCH:
        async with runtime.context.session_factory() as db:
            _, email, actor = await _rows(db, state, runtime)
            text = await onboarding_service.draft_onboarding_reply(
                db,
                email_service.get_llm(),
                email=email,
                requested=state.get("requested_fields", []),
                actor=actor,
                feedback=feedback,
            )
        # Nothing is retrieved: the reply asks for details, it states none.
        update: dict = {"draft_text": text, "grounded": False}
    elif branch == booking_service.BRANCH:
        # A template, no model call. What time the clinic told a patient to
        # turn up is not something a model gets to decide (§10.3).
        update = {
            "draft_text": booking_service.draft_booking_reply(
                name=state.get("patient_name"),
                doctor_name=state["booking_doctor_name"],
                slots=state["proposed_slots"],
            ),
            "grounded": False,
        }
    elif branch == prescription_service.BRANCH:
        # A template too (§12.3/G.16): the draft names no medicine, because
        # RESTRICTED_TERMS would block one and the patient would get nothing.
        update = {
            "draft_text": prescription_service.draft_prescription_reply(
                name=state.get("patient_name"),
                review_due=bool(state.get("prescription_review_due")),
            ),
            "grounded": False,
        }
    elif branch == records_service.BRANCH:
        # A template too (§11): there is nothing to generate, only an
        # acknowledgement to state, and no record content to state it from.
        update = {
            "draft_text": records_service.draft_records_reply(
                name=state.get("patient_name"),
                consent_on_file=bool(state.get("records_consent")),
            ),
            "grounded": False,
        }
    else:
        async with runtime.context.session_factory() as db:
            task, email, actor = await _rows(db, state, runtime)
            retry = email_service.reformulator(db, actor)
            text, grounded = await email_service.generate_draft(
                db, task, email, actor, feedback=feedback, reformulate=retry
            )
        update = {
            "draft_text": text,
            "grounded": grounded,
            "retrieval_attempts": retry.attempts,
            "reformulated_query": retry.query,
            "retrieval_sufficient": retry.sufficient,
        }
    if revising:
        update["revision_count"] = state.get("revision_count", 0) + 1
    return update


async def critic(state: CaseState) -> dict:
    reason = critique(state.get("draft_text"), branch=state.get("branch"))
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
    grounded_on_retry = bool(state.get("reformulated_query") and state.get("retrieval_sufficient"))
    return {
        "risk_tier": email_service.reply_risk_tier(
            revision_count=state.get("revision_count", 0),
            grounded_on_retry=grounded_on_retry,
            is_provisional=bool(state.get("is_provisional")),
            branch=state.get("branch"),
        )
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
                automated=True,
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
