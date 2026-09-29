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
from app.models.call import Call
from app.models.case import IntakeCase
from app.models.email import Email
from app.models.email_conversation import OPEN_STAGES, ConversationStage
from app.models.patient import Patient
from app.models.task import Task, TaskCategory
from app.models.user import User
from app.services import (
    booking_service,
    consent_service,
    email_conversation_service,
    email_service,
    identity_service,
    onboarding_service,
    prescription_service,
    records_service,
    task_service,
    voicemail_service,
)
from app.services.audit_service import record_event
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


async def _actor(db: AsyncSession, runtime: Runtime[Context]) -> User:
    actor = await db.get(User, runtime.context.actor_id)
    if actor is None:
        raise LookupError("agent actor row missing")
    return actor


def _case_id(state: CaseState) -> UUID | None:
    return UUID(state["case_id"]) if state.get("case_id") else None


def _patient_id(state: CaseState) -> UUID | None:
    return UUID(state["patient_id"]) if state.get("patient_id") else None


async def load(state: CaseState, runtime: Runtime[Context]) -> dict:
    """Populate state from the rows ingest_email already committed."""
    if state["channel"] == "voicemail":
        return await _load_voicemail(state, runtime)
    async with runtime.context.session_factory() as db:
        task, email, _ = await _rows(db, state, runtime)
        case = await db.get(IntakeCase, email.case_id) if email.case_id else None
        patient = await db.get(Patient, case.patient_id) if case and case.patient_id else None
        conversation = (
            await email_conversation_service.open_for_case(db, email.case_id)
            if email_conversation_service.enabled()
            else None
        )
    # Only present when there is one, so a flag-off run's state is unchanged.
    linked = {"conversation_id": str(conversation.id)} if conversation else {}
    return linked | {
        "case_id": str(email.case_id) if email.case_id else None,
        "intent": task.category.value if task.category else None,
        "content": email.body,
        "sender_identifier": email.sender,
        "patient_id": str(patient.id) if patient else None,
        "patient_name": patient.name if patient else None,
        "patient_status": patient.status.value if patient else None,
        "is_provisional": patient.is_provisional if patient else None,
    }


async def _load_voicemail(state: CaseState, runtime: Runtime[Context]) -> dict:
    """The voicemail loader (spec §8): the Call row process() finished."""
    async with runtime.context.session_factory() as db:
        task = await db.get(Task, UUID(state["task_id"]))
        call = await db.get(Call, UUID(state["source_id"]))
        if task is None or call is None:
            raise LookupError(f"task/call missing for thread {state['source_id']}")
    return {
        "case_id": str(call.case_id),
        "intent": task.category.value if task.category else None,
        "content": call.transcript,
        "sender_identifier": call.phone_number,
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
            # The conversation flow also reads a name from the From header and
            # accepts an MRN from the patient's own address.
            **(
                {
                    "sender_name": email.sender_name,
                    "mrn": email_conversation_service.find_mrn(email.body),
                }
                if email_conversation_service.enabled()
                else {}
            ),
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
        "patient_name": patient.name,
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
        actor = await _actor(db, runtime)
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


def _patient_state(patient: Patient | None) -> dict:
    if patient is None:
        return {}
    return {
        "patient_id": str(patient.id),
        "patient_name": patient.name,
        "patient_status": patient.status.value,
        "is_provisional": patient.is_provisional,
    }


_AUTOMATIC_REASON = (
    "This is an automatic message (an out-of-office or a no-reply address), so it was "
    "not answered automatically."
)


async def conversation(state: CaseState, runtime: Runtime[Context]) -> dict:
    """One turn of an email conversation (email_conversation_service): the
    first appointment request, or any reply linked to an open conversation.

    Returns the fixed text to send and what to record once it is sent, or the
    offered time the patient picked (for book), or, after a verification
    reply identified the sender, the original inquiry to carry on with, or a
    hold for staff.
    """
    known = state.get("identity_fields") or {}
    async with runtime.context.session_factory() as db:
        _, email, actor = await _rows(db, state, runtime)
        # Before anything is created: an out-of-office must not open a
        # conversation that a later real email could be linked into.
        if not email_conversation_service.can_auto_reply(email):
            await record_event(
                db,
                actor=actor,
                case_id=_case_id(state),
                action="agent.booking_decision",
                details={"decision": "staff", "reason": "automatic_message"},
            )
            await task_service.hold_for_staff(db, state["task_id"], _AUTOMATIC_REASON)
            return {"dispatch_result": "conversation_hold"}
        row, created = await email_conversation_service.get_or_create(
            db,
            case_id=_case_id(state),
            intent=state["intent"],
            origin_email_id=email.id,
            patient_id=_patient_id(state),
            stage=ConversationStage.AWAITING_DETAILS,
        )
        conversation_id = str(row.id)
        if not created and row.stage not in OPEN_STAGES:
            # Booked, or already with staff: the agent's part is over. Without
            # this a matched patient's reply re-entered the automated turn and
            # got fresh offers over the head of the staff member handling it.
            await record_event(
                db,
                actor=actor,
                case_id=_case_id(state),
                action="agent.booking_decision",
                details={"decision": "staff", "reason": "closed", "stage": row.stage},
            )
            await task_service.hold_for_staff(
                db, state["task_id"], email_conversation_service.STAFF_REASONS["closed"]
            )
            return {"conversation_id": conversation_id, "dispatch_result": "conversation_hold"}
        turn = await email_conversation_service.handle_turn(
            db,
            email_service.get_llm(),
            conversation=row,
            email=email,
            actor=actor,
            first_turn=created,
            known=identity_service.IdentityFields(
                name=known.get("name"),
                dob=date.fromisoformat(known["dob"]) if known.get("dob") else None,
                phone=known.get("phone"),
            ),
        )
        if turn.decision == "staff":
            await task_service.hold_for_staff(
                db, state["task_id"], email_conversation_service.STAFF_REASONS[turn.reason]
            )
            return {"conversation_id": conversation_id, "dispatch_result": "conversation_hold"}
        patient = await db.get(Patient, row.patient_id) if row.patient_id else None
        original_intent = row.original_intent
        origin = str(row.origin_email_id) if row.origin_email_id else None
    update: dict = {"conversation_id": conversation_id, **_patient_state(patient)}
    if turn.decision == "resume":
        # Verified: carry on with what they first asked, routed the way
        # route_identity would have routed it had the sender been known then.
        return update | {
            "conversation_resume": True,
            "identity_outcome": identity_service.IdentityOutcome.MATCHED.value,
            "intent": original_intent,
            "content_email_id": origin,
        }
    if turn.decision == "book":
        return update | {"booking_choice": turn.choice}
    return update | {
        "branch": email_conversation_service.BRANCH,
        "template_text": turn.text,
        "next_stage": turn.next_stage,
        "offer": turn.offer,
    }


async def book(state: CaseState, runtime: Runtime[Context]) -> dict:
    """Turn 3: book the offered time the patient confirmed, if their record is
    bookable and the time is still free, then confirm it. Otherwise a human
    (email_conversation_service.book_choice)."""
    choice = state["booking_choice"]
    async with runtime.context.session_factory() as db:
        _, _, actor = await _rows(db, state, runtime)
        turn = await email_conversation_service.book_choice(
            db, conversation_id=state["conversation_id"], choice=choice, actor=actor
        )
        await record_event(
            db,
            actor=actor,
            case_id=_case_id(state),
            action="agent.booking_decision",
            details={
                "conversation_id": state["conversation_id"],
                "decision": turn.decision,
                "reason": turn.reason,
                "doctor_id": choice["doctor_id"],
                "time_slot": choice["start"],
            },
        )
        await db.commit()
        if turn.decision == "staff":
            await task_service.hold_for_staff(
                db, state["task_id"], email_conversation_service.STAFF_REASONS[turn.reason]
            )
            return {"dispatch_result": "conversation_hold"}
    return {
        "branch": email_conversation_service.BRANCH,
        "template_text": turn.text,
        "next_stage": ConversationStage.BOOKED.value,
        "offer": [],
    }


async def request_verification(state: CaseState, runtime: Runtime[Context]) -> dict:
    """A patient-specific inquiry from a sender who cannot be identified.

    Staff get the held Task exactly as identity_hold gives it to them, and at
    the same time the sender is asked for the details that would identify
    them, so they are not left waiting. Once per case, never to a machine.
    """
    async with runtime.context.session_factory() as db:
        _, email, actor = await _rows(db, state, runtime)
        await identity_service.hold_for_staff(
            db, state["task_id"], identity_service.IdentityOutcome(state["identity_outcome"])
        )
        row, _ = await email_conversation_service.get_or_create(
            db,
            case_id=_case_id(state),
            intent=state["intent"],
            origin_email_id=email.id,
            patient_id=None,
            stage=ConversationStage.AWAITING_VERIFICATION,
        )
        conversation_id = str(row.id)
        if not email_conversation_service.can_auto_reply(email):
            skipped = "automatic_message"
        elif (
            row.verification_sent_at is not None
            or row.stage != ConversationStage.AWAITING_VERIFICATION
        ):
            skipped = "verification_already_sent"
        else:
            skipped = None
        await record_event(
            db,
            actor=actor,
            case_id=_case_id(state),
            action="agent.verification_requested",
            details={
                "conversation_id": conversation_id,
                "sending": skipped is None,
                "skipped": skipped,
            },
        )
        await db.commit()
    if skipped:
        return {"dispatch_result": "identity_hold"}
    return {
        "conversation_id": conversation_id,
        "branch": email_conversation_service.VERIFICATION_BRANCH,
        "template_text": email_conversation_service.verification_text(),
        "next_stage": ConversationStage.AWAITING_VERIFICATION.value,
        "offer": [],
    }


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
    if branch in email_service.TEMPLATE_BRANCHES:
        # Fixed text the conversation node decided. A critic redraft gets the
        # same text back and ends in escalation, which is right for a
        # template the critic will not pass.
        update: dict = {"draft_text": state["template_text"], "grounded": False}
    elif branch == onboarding_service.BRANCH:
        async with runtime.context.session_factory() as db:
            _, email, actor = await _rows(db, state, runtime)
            text = await onboarding_service.draft_onboarding_reply(
                db,
                email_service.get_llm(),
                email=email,
                name=state["patient_name"],
                requested=state.get("requested_fields", []),
                actor=actor,
                feedback=feedback,
            )
        # Nothing is retrieved: the reply asks for details, it states none.
        update = {"draft_text": text, "grounded": False}
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
            if state.get("content_email_id"):
                # A verification reply only says who the sender is; the
                # question to answer is in the email that opened the case.
                email = await db.get(Email, UUID(state["content_email_id"])) or email
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
        await _record_conversation_send(db, state)
    return {"dispatch_result": "sent", "delivery_error": None}


async def _record_conversation_send(db: AsyncSession, state: CaseState) -> None:
    """A conversation reply went out: the next turn is checked against it."""
    if state.get("conversation_id") and state.get("branch") in email_service.TEMPLATE_BRANCHES:
        await email_conversation_service.record_sent(
            db,
            state["conversation_id"],
            text=state.get("draft_text"),
            next_stage=state.get("next_stage"),
            offer=state.get("offer"),
            verification=state["branch"] == email_conversation_service.VERIFICATION_BRANCH,
        )


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
        if sent:
            await _record_conversation_send(db, state)
    return {"dispatch_result": "sent" if sent else "send_failed"}


async def voicemail_identity(state: CaseState, runtime: Runtime[Context]) -> dict:
    """Caller ID + keypad DOB, one patient or nobody. The match is probable:
    it goes into state and the script, never onto the case."""
    async with runtime.context.session_factory() as db:
        actor = await _actor(db, runtime)
        call = await db.get(Call, UUID(state["source_id"]))
        if call is None:
            raise LookupError(f"call missing for thread {state['source_id']}")
        patient = (
            None
            if call.phone_number == voicemail_service.WITHHELD
            else await identity_service.match_phone_dob(db, call.phone_number, call.keypad_dob)
        )
        await record_event(
            db,
            case_id=call.case_id,
            actor=actor,
            action="voicemail.identity_resolved",
            details={"call_id": str(call.id), "probable_match": patient is not None},
        )
        await db.commit()
    if patient is None:
        return {"identity_outcome": identity_service.IdentityOutcome.NO_MATCH.value}
    return {
        "identity_outcome": identity_service.IdentityOutcome.MATCHED.value,
        "patient_id": str(patient.id),
        "patient_name": patient.name,
        "patient_status": patient.status.value,
        "is_provisional": patient.is_provisional,
    }


async def voicemail_onboarding(state: CaseState, runtime: Runtime[Context]) -> dict:
    """An unknown caller asking to book or join: the provisional patient email
    onboarding (§9.0) would create. The name comes from the transcript, the
    phone from caller ID and the DOB from the keypad only: spoken digits are
    the least reliable part of a transcript. Nothing here replies; the
    callback script tells staff to finish the registration."""
    async with runtime.context.session_factory() as db:
        actor = await _actor(db, runtime)
        call = await db.get(Call, UUID(state["source_id"]))
        if call is None:
            raise LookupError(f"call missing for thread {state['source_id']}")
        if (
            call.phone_number == voicemail_service.WITHHELD
            or not call.transcript
            or (call.transcript_quality or {}).get("low")
        ):
            return {}
        patient = await identity_service.find_provisional_by_phone(db, call.phone_number)
        outcome = "existing"
        if patient is None:
            said = await identity_service.extract_identity_fields(
                db, email_service.get_llm(), call.transcript, actor=actor
            )
            patient = await onboarding_service.start_onboarding(
                db,
                case_id=call.case_id,
                sender=None,
                fields=identity_service.IdentityFields(
                    name=said.name, dob=call.keypad_dob, phone=call.phone_number
                ),
                actor=actor,
            )
            outcome = "created"
        if patient is None:
            return {}  # no name to file a record under: staff confirm who called
    return {
        "voicemail_onboarding": outcome,
        "patient_id": str(patient.id),
        "patient_name": patient.name,
        "patient_status": patient.status.value,
        "is_provisional": True,
    }


async def callback(state: CaseState, runtime: Runtime[Context]) -> dict:
    """Terminal for voicemail: the callback script on the Task."""
    async with runtime.context.session_factory() as db:
        actor = await _actor(db, runtime)
        call = await db.get(Call, UUID(state["source_id"]))
        task = await db.get(Task, UUID(state["task_id"]))
        if call is None or task is None:
            raise LookupError(f"task/call missing for thread {state['source_id']}")
        task.handover_context = voicemail_service.callback_script(call, state)
        await record_event(
            db,
            case_id=call.case_id,
            actor=actor,
            action="voicemail.callback_ready",
            details={
                "call_id": str(call.id),
                "task_id": str(task.id),
                "probable_patient": bool(state.get("patient_id")),
                "slots_offered": len(state.get("proposed_slots") or []),
            },
        )
        await db.commit()
    return {"dispatch_result": "callback_ready"}
