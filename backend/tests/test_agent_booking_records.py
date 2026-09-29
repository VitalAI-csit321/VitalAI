"""Booking (build spec §10) and records (§11) branches of the agent graph.

Both are reached only from route_identity, after the sender is known, and
both draft from a template: no model decides what time a patient was told to
come in, or what the clinic promised about their file. Both are HIGH risk, so
neither can auto-send. The booking agent proposes and stops; nothing in the
agent layer books an appointment.
"""

import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from app.agents import graph as agent_graph
from app.agents.graph import build_graph, run_config, thread_id
from app.config import settings
from app.models.approval import ApprovalRequest
from app.models.assignment import DoctorPatientAssignment
from app.models.audit import AuditEvent
from app.models.case import IntakeCase
from app.models.consent import ConsentStatus
from app.models.patient import Patient, PatientStatus
from app.models.task import Task, TaskCategory
from app.services import appointment_service, booking_service, consent_service, records_service
from app.services.task_routing_gate import TaskRoutingGateResult, TaskRoutingOutcome
from tests.agent_fakes import FakeLLM, seed_email


@pytest.fixture(autouse=True)
def _conversation_flow_off(monkeypatch):
    """These tests pin the routing that email_booking_conversation_enabled
    replaces (onboarding, the §10 proposal, a silent staff hold). The flag-on
    versions are in tests/test_email_conversation.py."""
    monkeypatch.setattr(settings, "email_booking_conversation_enabled", False)


SYDNEY = ZoneInfo("Australia/Sydney")
# A confident, auto-routed outcome: the auto-send predicate would pass it, so
# only the HIGH risk tier stands between these drafts and the patient.
AUTO = TaskRoutingGateResult(outcome=TaskRoutingOutcome.AUTO_ROUTED, override_reason=None)
_LINK = re.compile(r"https?://|www\.|\.com\b|\.au\b|reference|ref no|\bref\b", re.IGNORECASE)


@pytest.fixture(autouse=True)
def clinic_hours(monkeypatch):
    monkeypatch.setattr(settings, "clinic_open_hour", 8)
    monkeypatch.setattr(settings, "clinic_close_hour", 18)
    monkeypatch.setattr(settings, "clinic_timezone", "Australia/Sydney")
    monkeypatch.setattr(settings, "default_appointment_duration_minutes", 30)


@pytest.fixture
def guards(monkeypatch):
    """Every way these branches could reach a model, retrieval or a mailbox,
    made loud. A test that trips one fails rather than calling it for real."""
    llm = FakeLLM(worthy=True)
    monkeypatch.setattr("app.services.email_service.get_llm", lambda: llm)
    monkeypatch.setattr(settings, "outlook_enabled", True)
    monkeypatch.setattr("app.services.outlook_auth.get_access_token", AsyncMock(return_value="t"))
    sends = AsyncMock(return_value=None)
    monkeypatch.setattr("app.services.outlook_client.send_reply", sends)
    for target in (
        "app.rag.retrieval.retrieve",
        "app.rag.answer.answer_question",
        "app.rag.answer.get_llm",
        "app.services.email_service.generate_draft",
    ):
        monkeypatch.setattr(target, AsyncMock(side_effect=AssertionError(f"{target} called")))
    return llm, sends


async def _patient(db, name="Jane Smith", **extra) -> Patient:
    count = (await db.execute(select(func.count()).select_from(Patient))).scalar_one()
    patient = Patient(
        mrn=f"MRN-BK{count:04d}",
        name=name,
        status=extra.pop("status", PatientStatus.ACTIVE),
        **extra,
    )
    db.add(patient)
    await db.commit()
    return patient


async def _linked_case(db, patient: Patient) -> IntakeCase:
    """A case staff already attached to the patient: MATCHED, no extraction
    call (Appendix F.36)."""
    case = IntakeCase(
        patient_id=patient.id,
        patient_name=patient.name,
        contact_reason="Question",
        contact_channel="email",
    )
    db.add(case)
    await db.commit()
    return case


async def _assign(db, doctor, patient, admin) -> None:
    db.add(
        DoctorPatientAssignment(doctor_id=doctor.id, patient_id=patient.id, assigned_by=admin.id)
    )
    await db.commit()


async def _run(db, agent_saver, category, *, case_id=None, sender="jane@example.com", body=""):
    email, task = await seed_email(
        db,
        category=category,
        case_id=case_id,
        sender=sender,
        body=body or "Hello.",
        external_id=f"outlook-{uuid4()}",
    )
    await agent_graph.start(task.id, email.id, None, AUTO, 0.97)
    snapshot = (
        await build_graph()
        .compile(checkpointer=agent_saver)
        .aget_state(run_config(thread_id("email", str(email.id))))
    )
    await db.refresh(task)
    return email, task, snapshot


async def _approvals(db, task: Task) -> list[ApprovalRequest]:
    rows = (await db.execute(select(ApprovalRequest))).scalars().all()
    return [r for r in rows if r.payload.get("task_id") == str(task.id)]


def _assert_no_invention(text: str) -> None:
    assert not _LINK.search(text), text
    # No date or number the clinic did not decide: the records template names none.
    assert not re.search(r"\d", text), text


# --- booking ---------------------------------------------------------------------------


async def test_matched_patient_gets_three_clinic_local_proposals_and_one_approval(
    db_session, agent_saver, guards, admin_user, doctor_user
):
    """Gate (d)."""
    llm, sends = guards
    patient = await _patient(db_session)
    await _assign(db_session, doctor_user, patient, admin_user)
    case = await _linked_case(db_session, patient)

    email, task, snapshot = await _run(
        db_session,
        agent_saver,
        TaskCategory.APPOINTMENT_REQUEST,
        case_id=case.id,
        body="Can I get an appointment next week please?",
    )

    # First, before anything that could fail for another reason: the draft
    # did not leave the building, and it is waiting on exactly one human.
    sends.assert_not_awaited()
    assert task.draft_sent is False
    assert snapshot.next == ("await_approval",)
    (approval,) = await _approvals(db_session, task)

    values = snapshot.values
    assert values["branch"] == "booking"
    assert values["booking_doctor_name"] == doctor_user.full_name
    slots = [datetime.fromisoformat(s).astimezone(SYDNEY) for s in values["proposed_slots"]]
    assert [(s.hour, s.minute) for s in slots] == [(8, 0), (8, 30), (9, 0)]
    assert len({s.date() for s in slots}) == 1
    first_day = slots[0].date()
    assert first_day > datetime.now(SYDNEY).date()
    assert first_day.weekday() < 5
    assert first_day - datetime.now(SYDNEY).date() <= timedelta(days=3)

    assert values["risk_tier"] == "high"
    draft = approval.payload["draft"]
    assert draft == task.draft_text
    assert "Hi Jane," in draft
    assert f"Dr {doctor_user.full_name}" in draft
    for local in slots:
        assert booking_service.format_slot(local) in draft
    assert "8:00am" in draft and "9:00am" in draft
    assert "Nothing has been booked" in draft
    assert llm.draft_prompts == []


async def test_a_full_diary_proposes_what_exists_and_never_pads(
    db_session, admin_user, doctor_user, monkeypatch
):
    """Two free slots in the horizon: two proposals, not three."""
    monkeypatch.setattr(settings, "clinic_close_hour", 10)
    patient = await _patient(db_session)
    case = await _linked_case(db_session, patient)
    day = date(2026, 9, 1)  # a Tuesday

    await appointment_service.book_appointment(
        db_session,
        doctor_id=doctor_user.id,
        case_id=case.id,
        time_slot=datetime(2026, 9, 1, 8, 0, tzinfo=SYDNEY),
        actor=admin_user,
        duration_minutes=60,
    )

    slots = await booking_service.find_slots(
        db_session, admin_user, doctor_user.id, from_date=day, horizon_days=1
    )

    assert [s.astimezone(SYDNEY).strftime("%H:%M") for s in slots] == ["09:00", "09:30"]


async def test_no_assigned_doctor_is_a_hold_with_a_reason_and_no_draft(
    db_session, agent_saver, guards, admin_user
):
    """Gate (e), first half. Proposing a doctor the patient has no care
    relationship with is worse than saying nothing."""
    _, sends = guards
    patient = await _patient(db_session)
    case = await _linked_case(db_session, patient)

    email, task, snapshot = await _run(
        db_session, agent_saver, TaskCategory.APPOINTMENT_REQUEST, case_id=case.id
    )

    assert snapshot.values["dispatch_result"] == "booking_hold"
    assert "proposed_slots" not in snapshot.values
    assert snapshot.next == ()
    assert task.draft_text is None
    assert task.handover_context == booking_service.NO_DOCTOR_REASON
    assert await _approvals(db_session, task) == []
    sends.assert_not_awaited()
    assert task.draft_sent is False


async def test_no_free_slot_in_the_horizon_is_a_hold_not_an_empty_proposal(
    db_session, agent_saver, guards, admin_user, doctor_user, monkeypatch
):
    """Gate (e), second half. A clinic day with no bookable hours has no free
    slot on any of the fourteen days scanned."""
    _, sends = guards
    monkeypatch.setattr(settings, "clinic_close_hour", 8)
    patient = await _patient(db_session)
    await _assign(db_session, doctor_user, patient, admin_user)
    case = await _linked_case(db_session, patient)

    email, task, snapshot = await _run(
        db_session, agent_saver, TaskCategory.APPOINTMENT_REQUEST, case_id=case.id
    )

    assert snapshot.values["dispatch_result"] == "booking_hold"
    assert task.draft_text is None
    assert task.handover_context == booking_service.NO_SLOTS_REASON
    assert str(booking_service.HORIZON_DAYS) in task.handover_context
    assert await _approvals(db_session, task) == []
    sends.assert_not_awaited()
    assert task.draft_sent is False


async def test_unknown_sender_asking_to_book_reaches_onboarding_not_slots(
    db_session, agent_saver, guards, doctor_user
):
    """Gate (f), first half. Identity runs after the reply gate: wiring booking
    at route_intent would propose times to someone nobody has identified."""
    llm, sends = guards
    llm.identity = {"name": "Alex Stranger", "dob": "1990-01-01"}
    llm.replies = ["Thanks Alex. Please reply with a phone number we can reach you on."]

    email, task, snapshot = await _run(
        db_session,
        agent_saver,
        TaskCategory.APPOINTMENT_REQUEST,
        sender="alex@example.com",
        body="Alex Stranger, born 1990-01-01. Can I book in?",
    )

    assert snapshot.values["identity_outcome"] == "no_match"
    assert snapshot.values["branch"] == "onboarding"
    assert "proposed_slots" not in snapshot.values
    assert snapshot.next == ("await_approval",)
    sends.assert_not_awaited()
    assert task.draft_sent is False


async def test_a_provisional_patient_asking_to_book_reaches_staff(
    db_session, agent_saver, guards, admin_user, doctor_user
):
    """Gate (f), second half."""
    _, sends = guards
    patient = await _patient(db_session, is_provisional=True, status=PatientStatus.PENDING)
    await _assign(db_session, doctor_user, patient, admin_user)
    case = await _linked_case(db_session, patient)

    email, task, snapshot = await _run(
        db_session, agent_saver, TaskCategory.APPOINTMENT_REQUEST, case_id=case.id
    )

    assert "proposed_slots" not in snapshot.values
    assert task.draft_text is None
    assert await _approvals(db_session, task) == []
    sends.assert_not_awaited()
    assert task.draft_sent is False


async def test_a_failing_booking_node_takes_the_failure_path(
    db_session, agent_saver, guards, admin_user, doctor_user, monkeypatch
):
    """The branch is a DB-touching node, so it must be _guarded: an audit
    event and a reason on the Task, not a thread that dies in silence."""
    patient = await _patient(db_session)
    await _assign(db_session, doctor_user, patient, admin_user)
    case = await _linked_case(db_session, patient)
    monkeypatch.setattr(
        booking_service, "doctor_for_patient", AsyncMock(side_effect=RuntimeError("db gone"))
    )

    email, task, snapshot = await _run(
        db_session, agent_saver, TaskCategory.APPOINTMENT_REQUEST, case_id=case.id
    )

    assert snapshot.values["error"] == "booking: RuntimeError"
    assert "booking" in task.handover_context
    events = (
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.case_id == case.id, AuditEvent.action == "agent.node_failed"
                )
            )
        )
        .scalars()
        .all()
    )
    assert [e.details["stage"] for e in events] == ["booking"]


def test_nothing_in_the_agent_layer_books_an_appointment():
    """Gate (j). The §10 agent proposes; a human confirming is the only way in.

    One deliberate exception (Amin, 2026-09-24): the email booking
    conversation books a time the patient confirmed in writing, behind
    email_booking_conversation_enabled, through
    email_conversation_service.book_choice. Exactly one call there, and still
    none anywhere in app/agents."""
    app_dir = Path(__file__).resolve().parent.parent / "app"
    call_sites = sorted(
        str(p.relative_to(app_dir))
        for p in app_dir.rglob("*.py")
        for _ in re.finditer(r"(?<!def )\bbook_appointment\(", p.read_text())
    )
    assert call_sites == [
        "services/appointment_service.py",
        "services/email_conversation_service.py",
    ]
    agents = [
        str(p.relative_to(app_dir))
        for p in (app_dir / "agents").rglob("*.py")
        # A call, or a reference that could be passed on and called.
        # Prose in a docstring saying the agent must not book is neither.
        if re.search(
            r"\bbook_appointment(_series)?\s*\(|\.book_appointment(_series)?\b"
            r"|import[^\n]*\bbook_appointment",
            p.read_text(),
        )
    ]
    assert agents == []


# --- records ---------------------------------------------------------------------------


async def _records(db_session, agent_saver, case) -> tuple[Task, object]:
    email, task, snapshot = await _run(
        db_session,
        agent_saver,
        TaskCategory.MEDICAL_RECORDS_REQUEST,
        case_id=case.id,
        body="Could you please send me a copy of my medical records?",
    )
    return task, snapshot


async def _assert_one_approval_no_send(db_session, task, snapshot, sends, llm) -> str:
    # The send first, so nothing earlier can mask an auto-send.
    sends.assert_not_awaited()
    assert task.draft_sent is False
    assert snapshot.next == ("await_approval",)
    (approval,) = await _approvals(db_session, task)
    assert snapshot.values["branch"] == "records"
    assert snapshot.values["risk_tier"] == "high"
    assert llm.draft_prompts == []
    draft = approval.payload["draft"]
    _assert_no_invention(draft)
    return draft


async def test_records_request_without_consent_asks_for_it(db_session, agent_saver, guards):
    """Gate (g). Email cases usually have no consent record at all; that is an
    outcome here, not an error (Appendix F.2)."""
    llm, sends = guards
    patient = await _patient(db_session)
    case = await _linked_case(db_session, patient)

    task, snapshot = await _records(db_session, agent_saver, case)

    assert snapshot.values["records_consent"] is False
    draft = await _assert_one_approval_no_send(db_session, task, snapshot, sends, llm)
    assert draft == records_service.draft_records_reply(name="Jane Smith", consent_on_file=False)
    assert "written consent" in draft


@pytest.mark.parametrize("captured", [False, True], ids=["pending", "captured_anyway"])
async def test_an_implied_consent_record_is_not_consent(
    db_session, agent_saver, guards, admin_user, captured
):
    """Gate (g). Implied consent is the clinic noting that someone emailed.
    capture_consent accepts any PENDING record, including an implied one, so
    the type is checked as well as the status."""
    llm, sends = guards
    patient = await _patient(db_session)
    case = await _linked_case(db_session, patient)
    record = await consent_service.create_consent_record(
        db_session, case.id, admin_user, consent_type=consent_service.IMPLIED_INBOUND_CONTACT
    )
    if captured:
        await consent_service.capture_consent(db_session, record.id, admin_user)
        await db_session.commit()
        await db_session.refresh(record)
        assert record.status == ConsentStatus.CAPTURED

    task, snapshot = await _records(db_session, agent_saver, case)

    assert snapshot.values["records_consent"] is False
    draft = await _assert_one_approval_no_send(db_session, task, snapshot, sends, llm)
    assert "written consent" in draft


async def test_records_request_with_explicit_consent_gets_the_release_acknowledgement(
    db_session, agent_saver, guards, admin_user
):
    """Gate (h)."""
    llm, sends = guards
    patient = await _patient(db_session)
    case = await _linked_case(db_session, patient)
    record = await consent_service.create_consent_record(db_session, case.id, admin_user)
    await consent_service.capture_consent(db_session, record.id, admin_user)
    await db_session.commit()

    task, snapshot = await _records(db_session, agent_saver, case)

    assert snapshot.values["records_consent"] is True
    draft = await _assert_one_approval_no_send(db_session, task, snapshot, sends, llm)
    assert draft == records_service.draft_records_reply(name="Jane Smith", consent_on_file=True)
    assert "verify your identity" in draft
    assert "No records are attached" in draft


async def test_consent_captured_on_another_case_of_the_same_patient_counts(
    db_session, agent_saver, guards, admin_user
):
    """Gate (d), spec G.11. Real mail can never put the consent on the email's
    own case: ingest_email opens a new case per message and the Outlook
    connector passes no case_id. The question is about the patient."""
    llm, sends = guards
    patient = await _patient(db_session)
    earlier_case = await _linked_case(db_session, patient)
    record = await consent_service.create_consent_record(db_session, earlier_case.id, admin_user)
    await consent_service.capture_consent(db_session, record.id, admin_user)
    await db_session.commit()
    # The records email arrives on its own, brand new case, carrying no consent.
    case = await _linked_case(db_session, patient)

    task, snapshot = await _records(db_session, agent_saver, case)

    assert snapshot.values["records_consent"] is True
    draft = await _assert_one_approval_no_send(db_session, task, snapshot, sends, llm)
    assert draft == records_service.draft_records_reply(name="Jane Smith", consent_on_file=True)
    assert "verify your identity" in draft


async def test_an_implied_record_on_another_case_is_still_not_consent(
    db_session, agent_saver, guards, admin_user
):
    """Gate (d), the other half: asking the patient-level question must not
    turn the clinic noting an inbound email into authority to release a file."""
    llm, sends = guards
    patient = await _patient(db_session)
    earlier_case = await _linked_case(db_session, patient)
    record = await consent_service.create_consent_record(
        db_session,
        earlier_case.id,
        admin_user,
        consent_type=consent_service.IMPLIED_INBOUND_CONTACT,
    )
    await consent_service.capture_consent(db_session, record.id, admin_user)
    await db_session.commit()
    case = await _linked_case(db_session, patient)

    task, snapshot = await _records(db_session, agent_saver, case)

    assert snapshot.values["records_consent"] is False
    draft = await _assert_one_approval_no_send(db_session, task, snapshot, sends, llm)
    assert "written consent" in draft


async def test_a_failing_records_node_takes_the_failure_path(
    db_session, agent_saver, guards, monkeypatch
):
    patient = await _patient(db_session)
    case = await _linked_case(db_session, patient)
    monkeypatch.setattr(
        records_service, "has_explicit_consent", AsyncMock(side_effect=RuntimeError("db gone"))
    )

    task, snapshot = await _records(db_session, agent_saver, case)

    assert snapshot.values["error"] == "records: RuntimeError"
    events = (
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.case_id == case.id, AuditEvent.action == "agent.node_failed"
                )
            )
        )
        .scalars()
        .all()
    )
    assert [e.details["stage"] for e in events] == ["records"]


def test_both_branches_are_always_high_risk_and_only_they_are():
    from app.services.email_service import reply_risk_tier

    assert reply_risk_tier(revision_count=0, branch="booking") == "high"
    assert reply_risk_tier(revision_count=0, branch="records") == "high"
    # The live flag-off path never passes a branch; it must stay LOW there.
    assert reply_risk_tier(revision_count=0) == "low"
    assert reply_risk_tier(revision_count=0, branch="onboarding") == "low"


@pytest.mark.parametrize(
    ("full_name", "rendered"),
    [
        ("Aisha Rahman", "Dr Aisha Rahman has"),
        # How the demo corpus stores its doctors (ingest_appointment_history).
        ("Dr Aisha Rahman", "Dr Aisha Rahman has"),
        ("Dr. Aisha Rahman", "Dr. Aisha Rahman has"),
        ("Drew Carter", "Dr Drew Carter has"),
    ],
)
def test_the_doctor_is_titled_once(full_name, rendered):
    instant = datetime(2026, 8, 31, 22, 0, tzinfo=UTC).isoformat()
    text = booking_service.draft_booking_reply(name="Jane", doctor_name=full_name, slots=[instant])
    assert rendered in text
    assert not re.search(r"\bDr\.? Dr\b", text), text


def test_the_booking_template_renders_clinic_local_time():
    # 22:00 UTC on 31 August is 08:00 on Tuesday 1 September in Sydney.
    instant = datetime(2026, 8, 31, 22, 0, tzinfo=UTC).isoformat()
    text = booking_service.draft_booking_reply(name=None, doctor_name="Chen", slots=[instant])
    assert "Tuesday 1 September at 8:00am" in text
    assert "Hi there," in text
    assert "this time" in text
    assert not _LINK.search(text)


def test_neither_template_mentions_a_url_or_reference():
    for text in (
        records_service.draft_records_reply(name="Sam Lee", consent_on_file=False),
        records_service.draft_records_reply(name="Sam Lee", consent_on_file=True),
    ):
        _assert_no_invention(text)


@pytest.mark.parametrize(
    ("day", "open_"),
    [
        # NSW Labour Day. The black-box run was offered six slots on it; the
        # clinic is closed on NSW public holidays.
        (date(2026, 10, 5), False),
        (date(2026, 12, 25), False),
        (date(2026, 10, 3), False),  # Saturday
        (date(2026, 10, 6), True),
    ],
)
def test_public_holidays_and_weekends_are_not_clinic_days(day, open_):
    assert booking_service.is_clinic_day(day) is open_
