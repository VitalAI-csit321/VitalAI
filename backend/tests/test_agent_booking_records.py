"""Booking branch of the agent graph (build spec §10).

Reached only from route_identity, after the sender is known, and drafted from
a template: no model decides what time a patient was told to come in. HIGH
risk, so it cannot auto-send. The agent proposes and stops; nothing in the
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
from app.models.patient import Patient, PatientStatus
from app.models.task import Task, TaskCategory
from app.services import appointment_service, booking_service
from app.services.task_routing_gate import TaskRoutingGateResult, TaskRoutingOutcome
from tests.agent_fakes import FakeLLM, seed_email

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
    """Gate (j). The agent proposes; a human confirming is the only way in."""
    app_dir = Path(__file__).resolve().parent.parent / "app"
    call_sites = [
        str(p.relative_to(app_dir))
        for p in app_dir.rglob("*.py")
        for _ in re.finditer(r"(?<!def )\bbook_appointment\(", p.read_text())
    ]
    assert call_sites == ["services/appointment_service.py"]
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


def test_the_booking_branch_is_always_high_risk():
    from app.services.email_service import reply_risk_tier

    assert reply_risk_tier(revision_count=0, branch="booking") == "high"
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
