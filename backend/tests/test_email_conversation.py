"""The email conversation flow (email_conversation_service), flag on.

Every turn goes through the real ingest_email (so reply linking is exercised)
and the real graph. The model is FakeLLM: tests decide what it "read", and the
code under test decides what that is allowed to mean.
"""

import re
from datetime import UTC, date, datetime, time, timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.agents import graph as agent_graph
from app.agents.graph import route_identity
from app.config import settings
from app.models.appointment import Appointment, AppointmentStatus
from app.models.approval import ApprovalRequest
from app.models.assignment import DoctorPatientAssignment
from app.models.audit import AuditEvent
from app.models.call import Call
from app.models.case import IntakeCase
from app.models.email import Email
from app.models.email_conversation import ConversationStage, EmailConversation
from app.models.human_review import HumanReviewTask, TaskStatus, TaskType
from app.models.patient import Patient, PatientStatus
from app.models.task import Task
from app.models.user import User, UserRole
from app.schemas.call import CallRouteRequest
from app.schemas.email import EmailIngestRequest
from app.services import (
    appointment_service,
    booking_service,
    call_service,
    email_conversation_service,
    email_service,
    identity_service,
    own_appointment_service,
    patient_service,
)
from app.services.identity_service import IdentityFields, IdentityOutcome
from tests.agent_fakes import FakeLLM

SYDNEY = ZoneInfo("Australia/Sydney")
SENDER = "jane@example.com"


@pytest.fixture(autouse=True)
def clinic(monkeypatch):
    monkeypatch.setattr(settings, "clinic_open_hour", 8)
    monkeypatch.setattr(settings, "clinic_close_hour", 18)
    monkeypatch.setattr(settings, "clinic_timezone", "Australia/Sydney")
    monkeypatch.setattr(settings, "default_appointment_duration_minutes", 30)
    monkeypatch.setattr(settings, "agentic_pipeline_enabled", True)
    monkeypatch.setattr(settings, "email_booking_conversation_enabled", True)
    # These tests are the flow that asks for details by email; the registration
    # form link (test_patient_form_link.py) replaces its first reply.
    monkeypatch.setattr(settings, "patient_form_link_enabled", False)


@pytest.fixture
def llm(monkeypatch):
    fake = FakeLLM(category="appointment_request", confidence=0.95)
    monkeypatch.setattr("app.services.email_service.get_llm", lambda: fake)
    return fake


@pytest.fixture
def sends(monkeypatch):
    """Every message that would have reached Graph, in order: (message_id, text)."""
    monkeypatch.setattr(settings, "outlook_enabled", True)
    monkeypatch.setattr("app.services.outlook_auth.get_access_token", AsyncMock(return_value="t"))
    sent: list[tuple[str, str]] = []

    async def send_reply(token, message_id, body):
        sent.append((message_id, body))

    monkeypatch.setattr("app.services.outlook_client.send_reply", send_reply)
    return sent


def _weekday_ahead(days: int = 3) -> date:
    day = datetime.now(SYDNEY).date() + timedelta(days=days)
    while not appointment_service.is_clinic_day(day):
        day += timedelta(days=1)
    return day


async def _mail(
    db,
    actor,
    body: str,
    *,
    message_id: str,
    references: str | None = None,
    sender: str = SENDER,
    **extra,
) -> tuple[Email, Task]:
    """One inbound email through ingest and the graph, as the poller would."""
    email, task, gate, confidence = await email_service.ingest_email(
        db,
        EmailIngestRequest(
            sender=sender,
            recipient="clinic@example.com",
            subject="Appointment",
            body=body,
            external_id=f"outlook-{uuid4()}",
            external_source="outlook",
            internet_message_id=message_id,
            in_reply_to=references.split()[-1] if references else None,
            references=references,
            **extra,
        ),
        actor,
    )
    await agent_graph.start(task.id, email.id, actor.id, gate, confidence)
    await db.refresh(task)
    return email, task


async def _conversation(db, case_id) -> EmailConversation:
    row = (
        await db.execute(select(EmailConversation).where(EmailConversation.case_id == case_id))
    ).scalar_one()
    await db.refresh(row)
    return row


async def _approvals(db, task) -> list[ApprovalRequest]:
    rows = (await db.execute(select(ApprovalRequest))).scalars().all()
    return [r for r in rows if r.payload.get("task_id") == str(task.id)]


async def _first_turn(db, admin, llm, sends, *, name="Jane Citizen"):
    llm.identity = {"name": name, "dob": None, "phone": None}
    llm.booking = [{"intent": "unclear", "confidence": 0.3}]
    return await _mail(
        db,
        admin,
        f"Hi, can I get an appointment next week?\n\nThanks,\n{name}",
        message_id="<t1@example.com>",
    )


async def _offer(db, admin, llm, sends, day: date):
    email1, _ = await _first_turn(db, admin, llm, sends)
    llm.booking = [
        {
            "dob": "1990-02-01",
            "phone": "0412 345 678",
            "preferred_day": day.isoformat(),
            "intent": "change",
            "confidence": 0.9,
        }
    ]
    email2, task2 = await _mail(
        db,
        admin,
        f"DOB 1/2/1990, 0412 345 678. {day:%A} please.\n\nOn Tue, clinic wrote:\n> old",
        message_id="<t2@example.com>",
        references="<t1@example.com> <reply1@clinic>",
    )
    return email1, email2, task2


def _local_value(start_iso: str) -> str:
    return datetime.fromisoformat(start_iso).astimezone(SYDNEY).strftime("%Y-%m-%dT%H:%M")


# --- turn 1 ------------------------------------------------------------------------


async def test_turn_one_creates_the_profile_and_auto_sends_the_acknowledgement(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    email, task = await _first_turn(db_session, admin_user, llm, sends)

    case = await db_session.get(IntakeCase, email.case_id)
    patient = await db_session.get(Patient, case.patient_id)
    assert patient.is_provisional and patient.name == "Jane Citizen"
    assert patient.email == SENDER

    ((_, text),) = sends
    assert text.startswith("Hi Jane,")
    assert "The booking cannot be made until we have them" in text
    for asked in ("your date of birth", "a phone number", "the day you would prefer"):
        assert asked in text
    assert f"Your reference number (MRN) is {patient.mrn}" in text
    for never in ("medicare", "medication", "allerg", "insurance", "payment"):
        assert never not in text.lower()

    conversation = await _conversation(db_session, case.id)
    assert conversation.stage == ConversationStage.AWAITING_DETAILS
    assert conversation.last_outbound_text == text
    assert task.draft_sent is True
    assert await _approvals(db_session, task) == []


async def test_a_first_email_with_no_name_still_opens_the_case_and_asks_for_the_name(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    llm.identity = {"name": None, "dob": None, "phone": None}
    email, task = await _mail(
        db_session, admin_user, "Can I get an appointment please?", message_id="<n1@example.com>"
    )

    case = await db_session.get(IntakeCase, email.case_id)
    assert case.patient_id is None
    conversation = await _conversation(db_session, case.id)
    assert conversation.patient_id is None
    ((_, text),) = sends
    assert text.startswith("Hello,")
    assert "your full name" in text
    assert "MRN" not in text


async def test_a_first_booking_request_phrased_as_a_question_is_not_sent_to_staff(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    # "Could I book an appointment next Wednesday?" read as intent "question"
    # in the black-box run, so the plainest booking request went to staff.
    llm.identity = {"name": "Jane Citizen", "dob": None, "phone": None}
    llm.booking = [{"intent": "question", "confidence": 0.8}]
    email, task = await _mail(
        db_session,
        admin_user,
        "Could I book an appointment next week please?\n\nJane Citizen",
        message_id="<q1@example.com>",
    )

    conversation = await _conversation(db_session, email.case_id)
    assert conversation.stage == ConversationStage.AWAITING_DETAILS
    assert len(sends) == 1


def test_the_string_null_from_the_model_is_null_not_a_failed_extraction():
    # gemma2:2b wrote "chosen_time": "null"; the ValidationError threw away an
    # otherwise good extraction (afternoon, confirm, 0.9) as "unclear".
    extraction = email_conversation_service.BookingExtraction.model_validate_json(
        '{"chosen_time": "null", "preferred_day": "", "part_of_day": "afternoon", '
        '"doctor_name": "None", "intent": "change", "confidence": 0.9}'
    )

    assert extraction.chosen_time is None and extraction.preferred_day is None
    assert extraction.doctor_name is None
    assert (extraction.part_of_day, extraction.intent) == ("afternoon", "change")


@pytest.mark.parametrize(
    ("text", "model_day", "expected"),
    [
        # Received Sunday 27 Sep 2026. gemma2:2b answered today for "next
        # Wednesday" and yesterday for "next Tuesday" on every sample.
        ("next Wednesday morning", date(2026, 9, 27), date(2026, 9, 30)),
        ("next Tuesday arvo", date(2026, 9, 26), date(2026, 9, 29)),
        # A named weekday the model already got right is left alone,
        # including "Wednesday week".
        ("Wednesday week", date(2026, 10, 7), date(2026, 10, 7)),
        # Nothing named, or two named: the model's day stands.
        ("tomorrow", date(2026, 9, 28), date(2026, 9, 28)),
        ("I work Mondays, is Thursday ok?", date(2026, 10, 1), date(2026, 10, 1)),
        ("next Friday", None, None),
    ],
)
def test_a_named_weekday_overrides_a_model_day_that_is_not_that_weekday(text, model_day, expected):
    got = email_conversation_service.named_weekday(model_day, text, today=date(2026, 9, 27))

    assert got == expected


async def test_a_sign_up_request_with_no_name_is_asked_for_details_then_onboarded(
    db_session, agent_saver, admin_user, doctor_user, llm, sends, monkeypatch
):
    # The resumed inquiry takes the ordinary org-grounded draft path.
    monkeypatch.setattr("app.rag.retrieval.retrieve", AsyncMock(return_value=[]))
    # Black-box A2: "I want to become a patient, how do I sign up?" got no
    # reply at all and sat at LOW priority.
    llm.category = "new_patient_onboarding"
    llm.identity = {"name": None, "dob": None, "phone": None}
    email1, task1 = await _mail(
        db_session,
        admin_user,
        "Hi, I want to become a patient. How do I sign up?",
        message_id="<su1@example.com>",
    )
    ((_, text),) = sends
    assert "your full name" in text and "your date of birth" in text

    llm.identity = {"name": "Riley Newcomer", "dob": "1992-05-17", "phone": "0400 123 456"}
    llm.booking = [
        {
            "name": "Riley Newcomer",
            "dob": "1992-05-17",
            "phone": "0400 123 456",
            "intent": "unclear",
            "confidence": 0.9,
        }
    ]
    _, task2 = await _mail(
        db_session,
        admin_user,
        "Riley Newcomer, 17/05/1992, 0400 123 456",
        message_id="<su2@example.com>",
        references="<su1@example.com>",
    )

    case = await db_session.get(IntakeCase, email1.case_id)
    patient = await db_session.get(Patient, case.patient_id)
    assert patient.is_provisional and patient.name == "Riley Newcomer"
    assert task2.handover_context != email_conversation_service.STAFF_REASONS["verification_failed"]
    assert len(await _approvals(db_session, task2)) == 1


async def test_the_display_name_reaches_identity_extraction(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    llm.identity = {"name": "Jane Citizen"}
    await _mail(
        db_session,
        admin_user,
        "Can I get an appointment?",
        message_id="<d1@example.com>",
        sender_name="Jane Citizen",
    )

    (prompt,) = llm.identity_prompts
    assert "FROM DISPLAY NAME: Jane Citizen" in prompt


# --- turn 2 ------------------------------------------------------------------------


async def test_turn_two_links_by_headers_fills_the_profile_and_offers_that_day(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    day = _weekday_ahead()
    email1, email2, task2 = await _offer(db_session, admin_user, llm, sends, day)

    assert email2.case_id == email1.case_id
    case = await db_session.get(IntakeCase, email1.case_id)
    patient = await db_session.get(Patient, case.patient_id)
    assert (patient.dob, patient.phone) == (date(1990, 2, 1), "0412 345 678")

    conversation = await _conversation(db_session, case.id)
    assert conversation.stage == ConversationStage.AWAITING_CHOICE
    assert conversation.offered_slots
    assert {
        datetime.fromisoformat(s["start"]).astimezone(SYDNEY).date()
        for s in conversation.offered_slots
    } == {day}
    text = sends[-1][1]
    assert f"These times are available on {day:%A} {day.day} {day:%B}:" in text
    assert "Nothing has been booked yet." in text
    assert len(sends) == 2


async def test_a_full_requested_day_offers_the_nearest_days_instead(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    saturday = _weekday_ahead()
    while saturday.weekday() != 5:
        saturday += timedelta(days=1)

    await _offer(db_session, admin_user, llm, sends, saturday)

    text = sends[-1][1]
    assert f"We have nothing free on Saturday {saturday.day} {saturday:%B}." in text
    offered = {line for line in text.splitlines() if line.startswith("- ")}
    assert offered and not any("Saturday" in line or "Sunday" in line for line in offered)


async def test_the_assigned_doctor_is_searched_first(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    patient = Patient(
        mrn="MRN-ASSIGNED1",
        name="Jane Citizen",
        dob=date(1990, 2, 1),
        email=SENDER,
        phone="0412345678",
        status=PatientStatus.ACTIVE,
    )
    db_session.add(patient)
    await db_session.flush()
    db_session.add(
        DoctorPatientAssignment(
            doctor_id=doctor_user.id, patient_id=patient.id, assigned_by=admin_user.id
        )
    )
    await db_session.commit()

    pool = await email_conversation_service.booking_service.doctor_pool(db_session, patient.id)

    assert pool[0] == [(doctor_user.id, doctor_user.full_name)]


async def test_the_extraction_prompt_resolves_dates_in_sydney_and_labels_our_message(
    db_session, admin_user, llm
):
    case = IntakeCase(contact_reason="x", contact_channel="email")
    db_session.add(case)
    await db_session.flush()
    email = Email(
        case_id=case.id,
        sender=SENDER,
        recipient="clinic@example.com",
        subject="Re",
        # Monday 23:30 UTC is already Tuesday morning in Sydney.
        received_at=datetime(2026, 9, 21, 23, 30, tzinfo=UTC),
        body="Tomorrow arvo please.\n\nOn Mon, clinic wrote:\n> Tuesday 29 September at 9:00am",
    )
    conversation = EmailConversation(
        case_id=case.id,
        original_intent="appointment_request",
        stage="awaiting_choice",
        offered_slots=[],
        clarifications=0,
        last_outbound_text="THE CLINIC SAID THIS",
    )
    db_session.add_all([email, conversation])
    await db_session.commit()

    await email_conversation_service.extract(
        db_session, llm, email=email, conversation=conversation, actor=admin_user
    )

    (prompt,) = llm.booking_prompts
    assert "Tuesday 22 September 2026 at 09:30" in prompt
    new_part = prompt.split("THE PATIENT'S NEW MESSAGE:")[1].split("Respond with")[0]
    assert "Tomorrow arvo please." in new_part
    assert "29 September" not in new_part
    assert "THE CLINIC SAID THIS" in prompt.split("THE PATIENT'S NEW MESSAGE:")[0]


# --- turn 3 ------------------------------------------------------------------------


async def test_turn_three_books_an_offered_free_time_and_confirms(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    day = _weekday_ahead()
    email1, _, _ = await _offer(db_session, admin_user, llm, sends, day)
    conversation = await _conversation(db_session, email1.case_id)
    pick = conversation.offered_slots[0]
    llm.booking = [
        {"chosen_time": _local_value(pick["start"]), "intent": "confirm", "confidence": 0.95}
    ]

    email3, task3 = await _mail(
        db_session,
        admin_user,
        "The first one please",
        message_id="<t3@example.com>",
        references="<t1@example.com> <t2@example.com> <reply2@clinic>",
    )

    appointment = (
        await db_session.execute(select(Appointment).where(Appointment.case_id == email1.case_id))
    ).scalar_one()
    assert str(appointment.doctor_id) == pick["doctor_id"]
    booked = appointment.time_slot
    assert booked.replace(tzinfo=booked.tzinfo or UTC) == datetime.fromisoformat(pick["start"])
    assert appointment.appointment_type == "new_patient"
    conversation = await _conversation(db_session, email1.case_id)
    assert conversation.stage == ConversationStage.BOOKED
    assert conversation.confirmed_email_id == email3.id
    text = sends[-1][1]
    assert "Your appointment is booked for" in text
    assert "bring photo ID" in text
    assert task3.draft_sent is True
    actions = {
        e.action
        for e in (
            await db_session.execute(select(AuditEvent).where(AuditEvent.case_id == email1.case_id))
        ).scalars()
    }
    assert {"agent.booking_extraction", "agent.booking_decision", "appointment.booked"} <= actions


async def test_a_low_confidence_reply_in_an_open_conversation_still_books(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    # "The second one please." is nothing like a first email, so the
    # classifier's second opinion zeroed its confidence, HUMAN_REVIEW won in
    # route_intent, and the black-box patient was never booked.
    day = _weekday_ahead()
    email1, _, _ = await _offer(db_session, admin_user, llm, sends, day)
    pick = (await _conversation(db_session, email1.case_id)).offered_slots[0]
    llm.confidence = 0.0
    llm.booking = [
        {"chosen_time": _local_value(pick["start"]), "intent": "confirm", "confidence": 0.95}
    ]

    await _mail(
        db_session,
        admin_user,
        "The first one please",
        message_id="<lc3@example.com>",
        references="<t1@example.com> <t2@example.com>",
    )

    assert (await _conversation(db_session, email1.case_id)).stage == ConversationStage.BOOKED


async def test_a_red_flag_in_an_open_conversation_still_goes_to_a_person(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    day = _weekday_ahead()
    email1, _, _ = await _offer(db_session, admin_user, llm, sends, day)
    pick = (await _conversation(db_session, email1.case_id)).offered_slots[0]
    llm.booking = [
        {"chosen_time": _local_value(pick["start"]), "intent": "confirm", "confidence": 0.95}
    ]
    sent_before = len(sends)

    await _mail(
        db_session,
        admin_user,
        "The first one please. I've also had chest pain since this morning.",
        message_id="<rf3@example.com>",
        references="<t1@example.com> <t2@example.com>",
    )

    assert (await _conversation(db_session, email1.case_id)).stage != ConversationStage.BOOKED
    # Nothing from the booking flow; only the fixed urgent notice goes out.
    assert [text for _, text in sends[sent_before:]] == [
        email_conversation_service.urgent_notice_text()
    ]


async def test_the_slot_the_patient_names_is_booked_whatever_the_model_picked(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    # Black-box run: "The second one please." -> the model answered the sixth
    # offered time, and 10:30am was booked and confirmed instead of 8:30am.
    day = _weekday_ahead()
    email1, _, _ = await _offer(db_session, admin_user, llm, sends, day)
    slots = (await _conversation(db_session, email1.case_id)).offered_slots
    llm.booking = [
        {"chosen_time": _local_value(slots[-1]["start"]), "intent": "confirm", "confidence": 0.9}
    ]

    await _mail(
        db_session,
        admin_user,
        "The second one please.",
        message_id="<s3@example.com>",
        references="<t1@example.com> <t2@example.com>",
    )

    appointment = (
        await db_session.execute(select(Appointment).where(Appointment.case_id == email1.case_id))
    ).scalar_one()
    booked = appointment.time_slot
    assert booked.replace(tzinfo=booked.tzinfo or UTC) == datetime.fromisoformat(slots[1]["start"])


async def test_a_named_slot_the_patient_turns_down_is_not_booked(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    day = _weekday_ahead()
    email1, _, _ = await _offer(db_session, admin_user, llm, sends, day)
    llm.booking = [{"intent": "change", "confidence": 0.9}]

    await _mail(
        db_session,
        admin_user,
        "The second one doesn't suit me, sorry.",
        message_id="<d3@example.com>",
        references="<t1@example.com> <t2@example.com>",
    )

    assert (await _conversation(db_session, email1.case_id)).stage != ConversationStage.BOOKED


_SLOTS = [
    {"start": "2026-09-29T22:00:00+00:00"},  # Wed 30 Sep 8:00am Sydney
    {"start": "2026-09-29T22:30:00+00:00"},  # 8:30am
    {"start": "2026-09-30T00:00:00+00:00"},  # 10:00am
    {"start": "2026-09-30T00:30:00+00:00"},  # 10:30am
]


@pytest.mark.parametrize(
    ("text", "index"),
    [
        ("The second one please.", 1),
        ("2nd option works for me", 1),
        ("Option 3 please", 2),
        ("I'll take the last one", 3),
        ("The first one, thanks", 0),
        ("8:30 is perfect", 1),
        ("10am please", 2),
        ("Can I do 10:30am?", 3),
        # Nothing clear: the model's pick stands.
        ("Sounds good", None),
        ("The first or second one, whichever", None),
        ("Is 7:15 possible?", None),
        ("First, can I ask whether parking is free?", None),
        ("On 30 September please", None),
    ],
)
def test_the_slot_named_in_the_text(text, index):
    got = email_conversation_service.slot_named_in(text, _SLOTS)

    assert got == (_SLOTS[index] if index is not None else None)


async def test_a_time_we_never_offered_gets_one_clarification_then_staff(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    day = _weekday_ahead()
    email1, _, _ = await _offer(db_session, admin_user, llm, sends, day)
    llm.booking = [
        {"chosen_time": f"{day.isoformat()}T07:15", "intent": "confirm", "confidence": 0.95}
    ]

    await _mail(
        db_session,
        admin_user,
        "7:15 please",
        message_id="<u1@example.com>",
        references="<t1@example.com>",
    )
    assert "not one of the times we offered" in sends[-1][1]
    count = len(sends)

    _, task = await _mail(
        db_session,
        admin_user,
        "7:15!",
        message_id="<u2@example.com>",
        references="<t1@example.com>",
    )

    assert len(sends) == count
    assert task.handover_context == email_conversation_service.STAFF_REASONS["unoffered"]
    assert (await _conversation(db_session, email1.case_id)).stage == ConversationStage.STAFF
    assert (
        await db_session.execute(select(Appointment).where(Appointment.case_id == email1.case_id))
    ).first() is None


async def _registered_patient(db, admin, doctor) -> Patient:
    patient = Patient(
        mrn="MRN-REGIST01",
        name="Jane Citizen",
        dob=date(1990, 2, 1),
        email=SENDER,
        phone="0412345678",
        status=PatientStatus.ACTIVE,
    )
    db.add(patient)
    await db.flush()
    db.add(
        DoctorPatientAssignment(doctor_id=doctor.id, patient_id=patient.id, assigned_by=admin.id)
    )
    await db.commit()
    return patient


async def test_once_staff_have_a_conversation_the_agent_sends_nothing_more(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    # Black-box run: a registered patient's first turn went to staff
    # (doctor_not_found), then each threaded reply still reached the automated
    # turn, and a clarification and new offers went out over staff's head.
    await _registered_patient(db_session, admin_user, doctor_user)
    llm.identity = {"name": "Jane Citizen", "dob": "1990-02-01", "phone": None}
    day = _weekday_ahead()
    llm.booking = [
        {
            "preferred_day": day.isoformat(),
            "doctor_name": "Dr Nobody",
            "intent": "change",
            "confidence": 0.9,
        }
    ]
    email1, _ = await _mail(
        db_session,
        admin_user,
        "Jane Citizen, DOB 1/2/1990. Can I see Dr Nobody?",
        message_id="<w1@example.com>",
    )
    assert (await _conversation(db_session, email1.case_id)).stage == ConversationStage.STAFF
    llm.booking = [{"preferred_day": day.isoformat(), "intent": "change", "confidence": 0.95}]

    _, task = await _mail(
        db_session,
        admin_user,
        "Jane Citizen, DOB 1/2/1990. Anyone that day is fine.",
        message_id="<w2@example.com>",
        references="<w1@example.com>",
    )

    assert sends == []
    assert task.handover_context == email_conversation_service.STAFF_REASONS["closed"]


async def _second_doctor(db) -> User:
    doctor = User(
        email="hannah.fitzgerald@example.com",
        hashed_password="x",
        full_name="Hannah Fitzgerald",
        role=UserRole.DOCTOR,
    )
    db.add(doctor)
    await db.commit()
    return doctor


async def _offered_by_own_gp(db, admin, doctor, llm):
    await _registered_patient(db, admin, doctor)
    llm.identity = {"name": "Jane Citizen", "dob": "1990-02-01", "phone": None}
    day = _weekday_ahead()
    llm.booking = [{"preferred_day": day.isoformat(), "intent": "change", "confidence": 0.9}]
    email1, _ = await _mail(
        db, admin, f"Jane Citizen. Any times on {day:%A}?", message_id="<g1@example.com>"
    )
    conversation = await _conversation(db, email1.case_id)
    assert {s["doctor_id"] for s in conversation.offered_slots} == {str(doctor.id)}
    return email1, day


async def test_asking_for_another_gp_offers_the_other_doctors_that_day(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    # Live run, Rachel Walker: "is it possible to book another GP?" got her own
    # GP's six times again, and "any other GP except Dr Priya Menon?" (a
    # question with no day) went to staff.
    hannah = await _second_doctor(db_session)
    email1, day = await _offered_by_own_gp(db_session, admin_user, doctor_user, llm)
    llm.booking = [{"intent": "question", "other_doctor": True, "confidence": 0.9}]

    await _mail(
        db_session,
        admin_user,
        "Is there any other GP I can book except my usual one?",
        message_id="<g2@example.com>",
        references="<g1@example.com>",
    )

    conversation = await _conversation(db_session, email1.case_id)
    assert conversation.stage == ConversationStage.AWAITING_CHOICE
    assert {s["doctor_id"] for s in conversation.offered_slots} == {str(hannah.id)}
    assert conversation.preferred_day == day
    assert "Hannah Fitzgerald" in sends[-1][1]


async def test_a_hand_written_reply_hands_the_conversation_back_to_the_agent(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    # Live run: staff answered by hand ("you can have Dr Hannah"), and the
    # patient's "Yes, Dr Hannah works" was closed with nothing sent.
    from app.services import inbox_service

    await _second_doctor(db_session)
    email1, day = await _offered_by_own_gp(db_session, admin_user, doctor_user, llm)
    llm.booking = [{"intent": "question", "confidence": 0.9}]
    _, task = await _mail(
        db_session,
        admin_user,
        "Is Dr Hannah any good?",
        message_id="<g3@example.com>",
        references="<g1@example.com>",
    )
    assert (await _conversation(db_session, email1.case_id)).stage == ConversationStage.STAFF

    staff_text = "Hello Jane, yes, you can see Dr Hannah Fitzgerald. Let us know."
    await inbox_service.write_reply(db_session, admin_user, task, staff_text)

    conversation = await _conversation(db_session, email1.case_id)
    assert conversation.stage == ConversationStage.AWAITING_CHOICE
    assert conversation.last_outbound_text == staff_text

    llm.booking = [{"doctor_name": "Hannah", "intent": "confirm", "confidence": 0.9}]
    await _mail(
        db_session,
        admin_user,
        "Yes, Dr Hannah works. Same day please.",
        message_id="<g4@example.com>",
        references="<g1@example.com>",
    )

    assert staff_text in llm.booking_prompts[-1]  # the staff reply is the context
    conversation = await _conversation(db_session, email1.case_id)
    assert conversation.stage == ConversationStage.AWAITING_CHOICE
    assert "Hannah Fitzgerald" in sends[-1][1]
    assert {s["start"][:10] for s in conversation.offered_slots} <= {
        day.isoformat(),
        (day - timedelta(days=1)).isoformat(),  # 8am Sydney is the day before in UTC
    }


async def test_the_patients_own_name_is_not_a_doctor_request(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    # gemma2:2b put "Daniel Okafor" (the patient) in doctor_name; no doctor
    # matched and a plain booking went to staff as doctor_not_found.
    await _registered_patient(db_session, admin_user, doctor_user)
    llm.identity = {"name": "Jane Citizen", "dob": "1990-02-01", "phone": None}
    llm.booking = [
        {
            "name": "Hi, Jane Citizen",
            "doctor_name": "Jane Citizen",
            "preferred_day": _weekday_ahead().isoformat(),
            "intent": "change",
            "confidence": 0.9,
        }
    ]

    email1, _ = await _mail(
        db_session,
        admin_user,
        "Hi, Jane Citizen, DOB 1/2/1990. Can I book in?",
        message_id="<o1@example.com>",
    )

    assert (
        await _conversation(db_session, email1.case_id)
    ).stage == ConversationStage.AWAITING_CHOICE


async def test_a_reply_after_booking_is_held_for_staff_and_books_nothing_more(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    # The confirmation tells the patient to reply to change it.
    await _registered_patient(db_session, admin_user, doctor_user)
    llm.identity = {"name": "Jane Citizen", "dob": "1990-02-01", "phone": None}
    day = _weekday_ahead()
    llm.booking = [{"preferred_day": day.isoformat(), "intent": "change", "confidence": 0.9}]
    email1, _ = await _mail(
        db_session,
        admin_user,
        "Jane Citizen, DOB 1/2/1990. Any time that day.",
        message_id="<k1@example.com>",
    )
    slots = (await _conversation(db_session, email1.case_id)).offered_slots
    llm.booking = [
        {"chosen_time": _local_value(slots[0]["start"]), "intent": "confirm", "confidence": 0.95}
    ]
    await _mail(
        db_session,
        admin_user,
        "Jane Citizen, DOB 1/2/1990. The first one please.",
        message_id="<k2@example.com>",
        references="<k1@example.com>",
    )
    assert (await _conversation(db_session, email1.case_id)).stage == ConversationStage.BOOKED
    sent_before = len(sends)
    llm.booking = [
        {"chosen_time": _local_value(slots[1]["start"]), "intent": "confirm", "confidence": 0.95}
    ]

    _, task = await _mail(
        db_session,
        admin_user,
        "Jane Citizen, DOB 1/2/1990. Actually the second one instead?",
        message_id="<k3@example.com>",
        references="<k1@example.com> <k2@example.com>",
    )

    assert len(sends) == sent_before
    booked = (
        (await db_session.execute(select(Appointment).where(Appointment.case_id == email1.case_id)))
        .scalars()
        .all()
    )
    assert len(booked) == 1
    assert task.handover_context == email_conversation_service.STAFF_REASONS["closed"]


async def test_a_changed_date_of_birth_is_questioned_once_then_staff(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    day = _weekday_ahead()
    email1, _, _ = await _offer(db_session, admin_user, llm, sends, day)
    llm.booking = [{"dob": "1991-03-04", "intent": "change", "confidence": 0.9}]

    await _mail(
        db_session,
        admin_user,
        "DOB 4/3/1991",
        message_id="<b1@example.com>",
        references="<t1@example.com>",
    )
    text = sends[-1][1]
    assert "does not match the details we have" in text
    assert text.startswith("Hello,")
    assert "1990" not in text

    _, task = await _mail(
        db_session,
        admin_user,
        "4/3/1991",
        message_id="<b2@example.com>",
        references="<t1@example.com>",
    )

    assert task.handover_context == email_conversation_service.STAFF_REASONS["dob_mismatch"]
    patient = await db_session.get(
        Patient, (await db_session.get(IntakeCase, email1.case_id)).patient_id
    )
    assert patient.dob == date(1990, 2, 1)


async def test_a_month_first_misreading_of_the_same_written_dob_is_not_a_mismatch(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    # The model turned "1/2/1990" into 1990-01-02; questioning a real patient
    # about their own birthday, then handing them to staff, was the result.
    day = _weekday_ahead()
    await _offer(db_session, admin_user, llm, sends, day)
    llm.booking = [{"dob": "1990-01-02", "intent": "change", "confidence": 0.9}]

    await _mail(
        db_session,
        admin_user,
        "Sorry, DOB is 1/2/1990 as I said.",
        message_id="<m1@example.com>",
        references="<t1@example.com>",
    )

    assert "does not match the details we have" not in sends[-1][1]


async def test_a_slot_taken_before_confirmation_goes_to_a_human(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    if db_session.bind.dialect.name == "sqlite":
        # get_availability's day window is compared as naive text on SQLite, so
        # an appointment early in the clinic day is invisible to it there (the
        # same reason test_a_full_diary_proposes_what_exists_and_never_pads
        # fails on SQLite at HEAD). Postgres, which CI runs, is the real check.
        pytest.skip("availability needs real timestamptz comparison")
    day = _weekday_ahead()
    email1, _, _ = await _offer(db_session, admin_user, llm, sends, day)
    pick = (await _conversation(db_session, email1.case_id)).offered_slots[0]
    other = IntakeCase(contact_reason="walk-in", contact_channel="phone")
    db_session.add(other)
    await db_session.commit()
    await appointment_service.book_appointment(
        db_session,
        doctor_id=UUID(pick["doctor_id"]),
        case_id=other.id,
        time_slot=datetime.fromisoformat(pick["start"]),
        actor=admin_user,
    )
    count = len(sends)
    llm.booking = [
        {"chosen_time": _local_value(pick["start"]), "intent": "confirm", "confidence": 0.95}
    ]

    _, task = await _mail(
        db_session,
        admin_user,
        "First one",
        message_id="<s1@example.com>",
        references="<t1@example.com>",
    )

    assert task.handover_context == email_conversation_service.STAFF_REASONS["slot_taken"]
    assert len(sends) == count
    assert (
        await db_session.execute(select(Appointment).where(Appointment.case_id == email1.case_id))
    ).first() is None


# --- verification ------------------------------------------------------------------


async def test_an_unidentified_records_request_gets_the_verification_email_and_continues(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    known = Patient(
        mrn="MRN-KNOWN001",
        name="Sam Known",
        dob=date(1985, 6, 7),
        email="sam@example.com",
        phone="0400000001",
        status=PatientStatus.ACTIVE,
    )
    db_session.add(known)
    await db_session.commit()
    llm.category = "medical_records_request"
    llm.identity = {"name": None}

    email1, task1 = await _mail(
        db_session,
        admin_user,
        "Please send me my records.",
        message_id="<r1@example.com>",
        sender="sam@example.com",
    )

    ((_, text),) = sends
    assert text.startswith("Hello,")
    assert "verify your profile and continue with your inquiry" in text
    assert "Sam" not in text and "records" not in text.lower()
    assert task1.handover_context  # staff still see it
    conversation = await _conversation(db_session, email1.case_id)
    assert conversation.stage == ConversationStage.AWAITING_VERIFICATION
    assert conversation.verification_sent_at is not None

    llm.booking = [
        {
            "name": "Sam Known",
            "dob": "1985-06-07",
            "phone": "0400 000 001",
            "intent": "unclear",
            "confidence": 0.9,
        }
    ]
    email2, task2 = await _mail(
        db_session,
        admin_user,
        "Sam Known, 7/6/1985, 0400 000 001",
        message_id="<r2@example.com>",
        references="<r1@example.com>",
        sender="sam@example.com",
    )

    assert email2.case_id == email1.case_id
    assert (await db_session.get(IntakeCase, email1.case_id)).patient_id == known.id
    assert (await _conversation(db_session, email1.case_id)).stage == ConversationStage.VERIFIED
    # Records always reach a human: the original inquiry carried on to approval.
    (approval,) = await _approvals(db_session, task2)
    assert "records" in approval.payload["draft"].lower()
    assert len(sends) == 1


async def test_a_verified_sender_closes_the_identity_item(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    known = Patient(
        mrn="MRN-KNOWN002",
        name="Sam Known",
        dob=date(1985, 6, 7),
        email="sam@example.com",
        phone="0400000001",
        status=PatientStatus.ACTIVE,
    )
    db_session.add(known)
    await db_session.commit()
    llm.category = "medical_records_request"
    llm.identity = {"name": None}
    email1, task1 = await _mail(
        db_session,
        admin_user,
        "Please send me my records.",
        message_id="<v1@example.com>",
        sender="sam@example.com",
    )
    (item,) = (
        await db_session.scalars(
            select(HumanReviewTask).where(
                HumanReviewTask.inbox_task_id == task1.id,
                HumanReviewTask.task_type == TaskType.IDENTITY_REVIEW,
            )
        )
    ).all()
    assert item.status == TaskStatus.PENDING

    llm.booking = [
        {
            "name": "Sam Known",
            "dob": "1985-06-07",
            "phone": "0400 000 001",
            "intent": "unclear",
            "confidence": 0.9,
        }
    ]
    await _mail(
        db_session,
        admin_user,
        "Sam Known, 7/6/1985, 0400 000 001",
        message_id="<v2@example.com>",
        references="<v1@example.com>",
        sender="sam@example.com",
    )

    assert (await db_session.get(IntakeCase, email1.case_id)).patient_id == known.id
    await db_session.refresh(item)
    assert item.status == TaskStatus.COMPLETED
    (done,) = [
        e
        for e in (
            await db_session.scalars(
                select(AuditEvent).where(AuditEvent.action == "review.completed")
            )
        ).all()
        if e.details["review_id"] == str(item.id)
    ]
    assert done.details["note"] == "Sender verified"


async def test_the_verification_email_goes_once_per_case_and_never_to_a_machine(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    llm.category = "results_enquiry"
    llm.identity = {"name": None}

    await _mail(
        db_session,
        admin_user,
        "Out of office until Monday.",
        message_id="<a1@example.com>",
        auto_submitted=True,
    )
    await _mail(
        db_session,
        admin_user,
        "Results?",
        message_id="<a2@example.com>",
        sender="noreply@example.com",
    )

    assert sends == []


async def _registered(db, *, email="kartik@example.com") -> Patient:
    patient = Patient(
        mrn="MRN-KARTIK01",
        name="Kartik Sangwan",
        dob=date(2009, 3, 23),
        email=email,
        phone="0470 979 616",
        status=PatientStatus.ACTIVE,
    )
    db.add(patient)
    await db.commit()
    return patient


async def _identity_item(db, task) -> HumanReviewTask:
    return (
        await db.scalars(
            select(HumanReviewTask).where(
                HumanReviewTask.inbox_task_id == task.id,
                HumanReviewTask.task_type == TaskType.IDENTITY_REVIEW,
            )
        )
    ).one()


async def test_a_staff_link_carries_on_with_the_original_booking_request(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    # A registered patient writing from a new address: the name alone is a
    # partial match, so they are asked to verify and staff see the item.
    patient = await _registered(db_session)
    day = _weekday_ahead()
    llm.identity = {"name": "Kartik Sangwan", "dob": None, "phone": None}
    email1, task1 = await _mail(
        db_session,
        admin_user,
        f"Can I book an appointment on {day:%A}? Thanks, Kartik Sangwan",
        message_id="<k1@example.com>",
        sender="kartik.work@example.com",
    )
    ((_, verification),) = sends
    assert "verify your profile" in verification
    item = await _identity_item(db_session, task1)

    from app.services import human_review_service

    await human_review_service.link_patient(db_session, item.id, admin_user, patient.id)
    llm.booking = [{"preferred_day": day.isoformat(), "intent": "change", "confidence": 0.9}]
    await agent_graph.rerun_after_review(item.id)

    # Without waiting for the patient: the times for the day they first asked for.
    assert len(sends) == 2
    offer = sends[1][1]
    assert offer.startswith("Hi Kartik,")
    assert "These times are available" in offer or "nearest available times" in offer
    conversation = await _conversation(db_session, email1.case_id)
    assert conversation.patient_id == patient.id
    assert conversation.stage == ConversationStage.AWAITING_CHOICE
    assert conversation.offered_slots


async def test_a_reply_after_a_staff_link_is_not_a_failed_verification(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    patient = await _registered(db_session)
    llm.identity = {"name": "Kartik Sangwan", "dob": None, "phone": None}
    email1, task1 = await _mail(
        db_session,
        admin_user,
        "I need an appointment. Kartik Sangwan",
        message_id="<k2@example.com>",
        sender="kartik.work@example.com",
    )
    item = await _identity_item(db_session, task1)
    from app.services import human_review_service

    await human_review_service.link_patient(db_session, item.id, admin_user, patient.id)

    # The patient answers before (or instead of) the re-run, with no details.
    llm.booking = [{"intent": "unclear", "confidence": 0.3}]
    _, task2 = await _mail(
        db_session,
        admin_user,
        "I am a current patient.",
        message_id="<k3@example.com>",
        references="<k2@example.com>",
        sender="kartik.work@example.com",
    )

    assert task2.handover_context != email_conversation_service.STAFF_REASONS["verification_failed"]
    conversation = await _conversation(db_session, email1.case_id)
    assert conversation.patient_id == patient.id
    assert conversation.stage == ConversationStage.AWAITING_DETAILS
    assert "the day you would prefer" in sends[-1][1]


async def test_the_inbox_shows_each_reply_not_the_first_email(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    from app.services import inbox_service

    await _registered(db_session, email=SENDER)
    llm.identity = {"name": "Kartik Sangwan", "dob": None, "phone": None}
    llm.booking = [{"intent": "unclear", "confidence": 0.3}]
    email1, task1 = await _mail(
        db_session,
        admin_user,
        "Can I get an appointment? Kartik Sangwan",
        message_id="<i1@example.com>",
    )
    email2, task2 = await _mail(
        db_session,
        admin_user,
        "Any time on Friday works.",
        message_id="<i2@example.com>",
        references="<i1@example.com>",
    )
    assert email2.case_id == email1.case_id

    first = await inbox_service._to_message(db_session, task1, admin_user)
    reply = await inbox_service._to_message(db_session, task2, admin_user)

    assert first.emailId == str(email1.id)
    assert reply.emailId == str(email2.id)
    assert reply.body == "Any time on Friday works."


async def test_a_verified_booking_offers_the_day_the_first_email_asked_for(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    """Amin's live run, 2026-10-06: the request for a day was in the first
    email, the details in the reply, and the clinic asked for the day again.
    The reply also came from Gmail's main address, not the +alias the first
    email used, which opened a second case and a second verification."""
    patient = await _registered(db_session, email="alex.hill@example.com")
    day = _weekday_ahead(10)
    llm.identity = {"name": "Kartik Sangwan", "dob": None, "phone": None}
    email1, _ = await _mail(
        db_session,
        admin_user,
        f"Could I get a booking on {day.day} {day:%B}? Can you let me know the slots? "
        "Kartik Sangwan",
        message_id="<h1@example.com>",
        sender="amin+kartik@example.com",
    )
    ((_, verification),) = sends
    assert "verify your profile" in verification

    llm.booking = [
        {
            "name": "Kartik Sangwan",
            "dob": "2009-03-23",
            "phone": "0470979616",
            "preferred_day": day.isoformat(),
            "intent": "unclear",
            "confidence": 0.9,
        }
    ]
    email2, _ = await _mail(
        db_session,
        admin_user,
        "Kartik Sangwan 23/03/2009 0470979616",
        message_id="<h2@example.com>",
        references="<h1@example.com>",
        sender="amin@example.com",
    )

    assert email2.case_id == email1.case_id
    assert f"{day.day} {day:%B}" in llm.booking_prompts[-1]  # the first email was read
    assert len(sends) == 2
    assert "These times are available" in sends[1][1] or "nearest available" in sends[1][1]
    conversation = await _conversation(db_session, email1.case_id)
    assert conversation.patient_id == patient.id
    assert conversation.stage == ConversationStage.AWAITING_CHOICE


def test_a_reply_links_across_plus_aliases_of_one_mailbox_only():
    who = email_conversation_service._mailbox
    assert who("Amin+Alexander.Hill@Gmail.com") == who("amin@gmail.com")
    assert who("amin@gmail.com") != who("amina@gmail.com")
    assert who("amin+x@gmail.com") != who("amin@outlook.com")


async def test_a_day_asked_as_a_question_mid_conversation_is_offered_times(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    # Live run: "Can you let me know the available slots on 24th of October?"
    # read as intent "question" with the day, and went to staff.
    email1, _ = await _first_turn(db_session, admin_user, llm, sends)
    day = _weekday_ahead(5)
    llm.booking = [
        {
            "dob": "1990-02-01",
            "phone": "0412 345 678",
            "preferred_day": day.isoformat(),
            "intent": "question",
            "confidence": 0.95,
        }
    ]
    await _mail(
        db_session,
        admin_user,
        f"DOB 1/2/1990, 0412 345 678. What times do you have on {day.day} {day:%B}?",
        message_id="<t2@example.com>",
        references="<t1@example.com>",
    )

    conversation = await _conversation(db_session, email1.case_id)
    assert conversation.stage == ConversationStage.AWAITING_CHOICE
    assert len(sends) == 2


async def _held(db, admin, llm, *, category="appointment_request"):
    """Rachel's live email: a plain booking request the classifier was not sure
    of, so it was held for a person and the agent never ran."""
    llm.category, llm.confidence = category, 0.5
    llm.identity = {"name": "Rachel Walker", "dob": None, "phone": None}
    email, task = await _mail(
        db,
        admin,
        "Hello, my name is Rachel Walker. Could I get a GP booking next week? Thank you.",
        message_id="<w1@example.com>",
        sender="rachel.walker@example.com",
    )
    (item,) = (
        await db.scalars(select(HumanReviewTask).where(HumanReviewTask.inbox_task_id == task.id))
    ).all()
    assert item.task_type == TaskType.ROUTING_REVIEW
    return email, task, item


async def test_confirming_a_held_category_carries_on_with_the_email(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    from app.services import human_review_service

    email, task, item = await _held(db_session, admin_user, llm)
    assert sends == []

    await human_review_service.claim_task(db_session, item.id, admin_user)
    await human_review_service.complete_task(db_session, item.id, admin_user, "Category confirmed")
    await agent_graph.rerun_after_review(item.id)

    ((_, text),) = sends
    assert text.startswith("Hi Rachel,")
    assert "We have received your appointment request" in text
    await db_session.refresh(task)
    assert task.handover_context is None  # the hold note no longer applies
    assert (await _conversation(db_session, email.case_id)).stage == (
        ConversationStage.AWAITING_DETAILS
    )


async def test_rerouting_a_held_email_runs_it_as_the_new_category(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    from app.models.task import TaskCategory
    from app.services import human_review_service

    _, _, item = await _held(db_session, admin_user, llm, category="general_administrative")

    await human_review_service.reroute(
        db_session, item.id, admin_user, TaskCategory.APPOINTMENT_REQUEST
    )
    await agent_graph.rerun_after_review(item.id)

    ((_, text),) = sends
    assert "We have received your appointment request" in text


async def test_rerouting_to_urgent_never_runs_the_agent(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    from app.models.task import TaskCategory
    from app.services import human_review_service

    _, task, item = await _held(db_session, admin_user, llm)

    await human_review_service.reroute(
        db_session, item.id, admin_user, TaskCategory.URGENT_EMERGENCY
    )
    await agent_graph.rerun_after_review(item.id)

    assert sends == []
    await db_session.refresh(task)
    assert task.draft_text is None


# --- linking and MRN -----------------------------------------------------------------


async def test_two_profiles_on_one_address_never_link_by_address(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    email1, _ = await _first_turn(db_session, admin_user, llm, sends)
    db_session.add(
        Patient(
            mrn="MRN-SIBLING1",
            name="Joe Citizen",
            email=SENDER,
            status=PatientStatus.PENDING,
            is_provisional=True,
        )
    )
    await db_session.commit()

    case = await email_conversation_service.find_case_for_reply(
        db_session, sender=SENDER, in_reply_to=None, references=None
    )
    by_header = await email_conversation_service.find_case_for_reply(
        db_session, sender=SENDER, in_reply_to=None, references="<x@y> <t1@example.com>"
    )
    from_someone_else = await email_conversation_service.find_case_for_reply(
        db_session, sender="other@example.com", in_reply_to="<t1@example.com>", references=None
    )

    assert case is None
    assert by_header.id == email1.case_id
    assert from_someone_else is None


async def test_the_address_fallback_links_a_single_open_conversation(
    db_session, agent_saver, admin_user, doctor_user, llm, sends
):
    email1, _ = await _first_turn(db_session, admin_user, llm, sends)

    case = await email_conversation_service.find_case_for_reply(
        db_session, sender=SENDER.upper(), in_reply_to=None, references=None
    )

    assert case.id == email1.case_id


async def test_an_mrn_matches_only_from_the_address_on_file(db_session):
    patient = Patient(
        mrn="MRN-ABCD1234", name="Jane Citizen", email=SENDER, status=PatientStatus.ACTIVE
    )
    db_session.add(patient)
    await db_session.commit()
    fields = IdentityFields(mrn="MRN-ABCD1234")

    own = await identity_service.resolve_patient(db_session, sender=SENDER, fields=fields)
    other = await identity_service.resolve_patient(
        db_session, sender="stranger@example.com", fields=fields
    )

    assert own.outcome == IdentityOutcome.MATCHED and own.patient.id == patient.id
    assert other.outcome != IdentityOutcome.MATCHED


# --- booking rules, call pipeline, flag off ---------------------------------------


async def test_a_provisional_patient_is_bookable_only_with_every_detail_and_confirmation():
    patient = Patient(
        name="Jane", email=SENDER, phone="0412", dob=date(1990, 1, 1), is_provisional=True
    )
    with pytest.raises(patient_service.ProvisionalPatientError):
        patient_service.assert_bookable(patient, confirmed_email_id=None)
    patient.phone = None
    with pytest.raises(patient_service.ProvisionalPatientError):
        patient_service.assert_bookable(patient, confirmed_email_id=uuid4())
    patient.phone = "0412"
    patient_service.assert_bookable(patient, confirmed_email_id=uuid4())


async def test_book_appointment_still_refuses_a_provisional_patient_by_default(
    db_session, admin_user, doctor_user
):
    case = IntakeCase(contact_reason="x", contact_channel="email")
    db_session.add(case)
    await db_session.commit()
    await patient_service.create_provisional_patient(
        db_session,
        case_id=case.id,
        name="Jane",
        email=SENDER,
        phone=None,
        dob=None,
        actor=admin_user,
    )

    with pytest.raises(patient_service.ProvisionalPatientError):
        await appointment_service.book_appointment(
            db_session,
            doctor_id=doctor_user.id,
            case_id=case.id,
            time_slot=datetime.now(UTC) + timedelta(days=3),
            actor=admin_user,
        )


class _CallLLM:
    async def ainvoke(self, prompt: str) -> str:
        if "IDENTITY DETAILS" in prompt:
            return '{"name": "Sam Caller", "dob": null, "phone": null}'
        return '{"category": "appointment_request", "confidence": 0.95}'


async def _routed_call(db, actor, monkeypatch) -> IntakeCase:
    monkeypatch.setattr("app.services.call_service.get_llm", lambda: _CallLLM())
    case = IntakeCase(contact_reason="call", contact_channel="phone")
    db.add(case)
    await db.flush()
    call = Call(
        case_id=case.id,
        phone_number="0499 111 222",
        transcript="Hi, this is Sam Caller, I'd like to book an appointment.",
    )
    db.add(call)
    await db.commit()
    await call_service.route_call(db, call.id, CallRouteRequest(), actor)
    await db.refresh(case)
    return case


async def test_a_call_with_phone_and_name_creates_the_provisional_profile(
    db_session, admin_user, monkeypatch
):
    case = await _routed_call(db_session, admin_user, monkeypatch)

    patient = await db_session.get(Patient, case.patient_id)
    assert patient.is_provisional
    assert (patient.name, patient.phone, patient.email) == ("Sam Caller", "0499 111 222", None)


async def test_with_the_flag_off_nothing_new_happens(db_session, admin_user, monkeypatch):
    monkeypatch.setattr(settings, "email_booking_conversation_enabled", False)

    case = await _routed_call(db_session, admin_user, monkeypatch)
    assert case.patient_id is None

    state = {"intent": "appointment_request", "identity_outcome": "no_match"}
    assert route_identity(state) == "onboarding"
    state = {"intent": "medical_records_request", "identity_outcome": "ambiguous"}
    assert route_identity(state) == "staff"
    assert email_service.reply_risk_tier(revision_count=0, branch="booking_conversation") == "low"


# --- the urgent notice -------------------------------------------------------------


async def test_an_urgent_email_is_acknowledged_and_still_waits_for_a_person(
    db_session, agent_saver, admin_user, llm, sends
):
    """Chest pain by email went to the queue and the sender heard nothing
    (2026-10-11). The clinic's policy is an immediate 000 redirect; the notice
    is fixed text, so no model words it, and it answers nothing: the task is
    not marked replied and a person still has to read the email."""
    email, task = await _mail(
        db_session,
        admin_user,
        "got a tight chest since this morning and feeling sweaty. any appointments today?",
        message_id="<urgent1@example.com>",
    )

    ((message_id, text),) = sends
    assert message_id == email.external_id
    assert text == email_conversation_service.urgent_notice_text()
    assert "our team will contact you as soon as they can" in text
    assert "call 000" in text
    assert task.draft_sent is False
    assert task.handover_context == email_conversation_service.URGENT_NOTICE_SENT


@pytest.mark.parametrize(
    "extra",
    [{"auto_submitted": True}, {"sender": "no-reply@pathology.example"}],
    ids=["out-of-office", "automated-sender"],
)
async def test_an_urgent_looking_automatic_email_gets_no_notice(
    db_session, agent_saver, admin_user, llm, sends, extra
):
    await _mail(
        db_session,
        admin_user,
        "URGENT: critical result available, chest pain clinic closed today.",
        message_id="<urgent2@example.com>",
        **extra,
    )

    assert sends == []


async def test_with_auto_send_off_an_urgent_email_gets_no_notice(
    db_session, agent_saver, admin_user, llm, sends, monkeypatch
):
    monkeypatch.setattr(settings, "email_auto_send_enabled", False)

    await _mail(
        db_session, admin_user, "I have chest pain right now.", message_id="<urgent3@example.com>"
    )

    assert sends == []


# --- a patient's own appointment ----------------------------------------------------
#
# The From address is all an email proves, and it can be forged. So nothing
# about an appointment is sent as a reply (a reply follows Reply-To): it goes
# as a new email to the address on the patient's record. And nothing is
# cancelled or moved on the first email: that email earns a one-time code,
# sent to the same address, which has to come back before the agent acts.


@pytest.fixture
def mails(monkeypatch, sends):
    """Every new (not reply) email that would have reached Graph: (to, body)."""
    sent: list[tuple[str, str]] = []

    async def send_mail(token, to_address, subject, body):
        sent.append((to_address, body))

    monkeypatch.setattr("app.services.outlook_client.send_mail", send_mail)
    return sent


def _code(text: str) -> str:
    return re.search(r"\b(\d{6})\b", text).group(1)


async def _with_appointment(db, admin, doctor, *days_ahead: int):
    """Jane, registered at SENDER, with an appointment at 10am on each given day."""
    patient = await _registered_patient(db, admin, doctor)
    booked = []
    for days in days_ahead:
        case = IntakeCase(
            patient_id=patient.id, contact_reason="booked by phone", contact_channel="phone"
        )
        db.add(case)
        await db.commit()
        when = datetime.combine(_weekday_ahead(days), time(10, 0), tzinfo=SYDNEY)
        booked.append(
            await appointment_service.book_appointment(
                db, doctor_id=doctor.id, case_id=case.id, time_slot=when, actor=admin
            )
        )
    return patient, booked


async def _review_items(db, task):
    return (
        (await db.execute(select(HumanReviewTask).where(HumanReviewTask.case_id == task.case_id)))
        .scalars()
        .all()
    )


async def test_a_patient_asking_when_their_appointment_is_gets_it_at_the_address_on_file(
    db_session, agent_saver, admin_user, doctor_user, llm, sends, mails
):
    """ "When is my appointment?" was answered "tell us the day you would
    prefer" (2026-10-11): the category said appointment, so it was a booking.
    The reply is filled from the diary; no model writes the time."""
    _, (appointment,) = await _with_appointment(db_session, admin_user, doctor_user, 5)
    llm.own_appointment = "ask"

    _, task = await _mail(
        db_session, admin_user, "what day and time is my appointment?", message_id="<own1@x>"
    )

    ((to, text),) = mails
    assert to == SENDER
    assert booking_service.format_slot(appointment.time_slot) in text
    assert booking_service.titled(doctor_user.full_name) in text
    assert sends == []  # never as a reply: a forged email can name its own Reply-To
    assert (task.draft_sent, task.draft_text) == (True, text)
    assert llm.booking_prompts == []


async def test_a_cancellation_is_only_carried_out_once_the_code_comes_back(
    db_session, agent_saver, admin_user, doctor_user, llm, sends, mails
):
    """Amin's calls (2026-10-11): the agent cancels by itself when one
    appointment can be meant and it is more than a day away, and, after the
    security review of that, only once the patient has returned the code sent
    to the address on their record."""
    _, (appointment,) = await _with_appointment(db_session, admin_user, doctor_user, 5)
    llm.own_appointment = "cancel"

    email1, _ = await _mail(
        db_session, admin_user, "pls cancel my appointment", message_id="<own2@x>"
    )

    await db_session.refresh(appointment)
    assert appointment.status != AppointmentStatus.CANCELLED
    ((to, asked),) = mails
    assert to == SENDER
    assert booking_service.format_slot(appointment.time_slot) in asked
    conversation = await _conversation(db_session, email1.case_id)
    assert conversation.stage == ConversationStage.AWAITING_CONFIRMATION
    assert conversation.appointment_id == appointment.id

    email2, _ = await _mail(
        db_session, admin_user, f"yes please, {_code(asked)}", message_id="<own2b@x>"
    )

    assert email2.case_id == email1.case_id
    await db_session.refresh(appointment)
    assert appointment.status == AppointmentStatus.CANCELLED
    assert mails[-1][0] == SENDER
    assert "has been cancelled" in mails[-1][1]
    assert (await _conversation(db_session, email1.case_id)).stage == ConversationStage.CLOSED
    assert sends == []


@pytest.mark.parametrize(
    "reply",
    ["yes cancel it", "the code is 000000", "That was not me, I did not ask for this. {code}"],
    ids=["no-code", "wrong-code", "declines"],
)
async def test_a_reply_that_does_not_confirm_cancels_nothing_and_goes_to_the_front_desk(
    db_session, agent_saver, admin_user, doctor_user, llm, sends, mails, reply
):
    _, (appointment,) = await _with_appointment(db_session, admin_user, doctor_user, 5)
    llm.own_appointment = "cancel"
    await _mail(db_session, admin_user, "pls cancel my appointment", message_id="<own3@x>")
    code = _code(mails[-1][1])
    wrong = "000000" if code != "000000" else "111111"

    _, task = await _mail(
        db_session,
        admin_user,
        reply.format(code=code).replace("000000", wrong),
        message_id="<own3b@x>",
    )

    await db_session.refresh(appointment)
    assert appointment.status != AppointmentStatus.CANCELLED
    assert len(mails) == 1
    assert own_appointment_service.UNCONFIRMED_REASON in [
        i.notes for i in await _review_items(db_session, task)
    ]


async def test_the_code_quoted_back_under_a_reply_confirms_nothing(
    db_session, agent_saver, admin_user, doctor_user, llm, sends, mails
):
    """Every mail client quotes the email it replies to, code included. Only
    what the sender wrote counts."""
    _, (appointment,) = await _with_appointment(db_session, admin_user, doctor_user, 5)
    llm.own_appointment = "cancel"
    await _mail(db_session, admin_user, "pls cancel my appointment", message_id="<own4@x>")
    asked = mails[-1][1]

    await _mail(
        db_session,
        admin_user,
        "ok\n\nOn Mon, the clinic wrote:\n" + "\n".join(f"> {line}" for line in asked.splitlines()),
        message_id="<own4b@x>",
    )

    await db_session.refresh(appointment)
    assert appointment.status != AppointmentStatus.CANCELLED


async def test_a_cancellation_inside_the_notice_period_is_left_to_the_front_desk(
    db_session, agent_saver, admin_user, doctor_user, llm, sends, mails, monkeypatch
):
    _, (appointment,) = await _with_appointment(db_session, admin_user, doctor_user, 5)
    monkeypatch.setattr(own_appointment_service, "MIN_NOTICE", timedelta(days=30))
    llm.own_appointment = "cancel"

    _, task = await _mail(
        db_session, admin_user, "pls cancel my appointment", message_id="<own5@x>"
    )

    await db_session.refresh(appointment)
    assert appointment.status != AppointmentStatus.CANCELLED
    ((to, text),) = mails
    assert to == SENDER
    assert "front desk will confirm" in text
    assert [i.notes for i in await _review_items(db_session, task)] == [
        own_appointment_service.late_reason(appointment, doctor_user.full_name)
    ]


async def test_with_two_appointments_an_unclear_one_is_asked_and_a_named_one_gets_a_code(
    db_session, agent_saver, admin_user, doctor_user, llm, sends, mails
):
    _, (first, second) = await _with_appointment(db_session, admin_user, doctor_user, 5, 9)
    llm.own_appointment = "cancel"

    await _mail(db_session, admin_user, "cancel my appointment please", message_id="<own6@x>")

    assert "more than one" in mails[-1][1]

    weekday = f"{second.time_slot.astimezone(SYDNEY):%A}"
    assert weekday != f"{first.time_slot.astimezone(SYDNEY):%A}"
    await _mail(db_session, admin_user, f"cancel the {weekday} one please", message_id="<own6b@x>")

    asked = mails[-1][1]
    assert booking_service.format_slot(second.time_slot) in asked
    assert booking_service.format_slot(first.time_slot) not in asked
    await _mail(db_session, admin_user, _code(asked), message_id="<own6c@x>")

    await db_session.refresh(first)
    await db_session.refresh(second)
    assert first.status != AppointmentStatus.CANCELLED
    assert second.status == AppointmentStatus.CANCELLED


async def test_a_cancellation_naming_a_day_they_have_nothing_on_is_checked_first(
    db_session, agent_saver, admin_user, doctor_user, llm, sends, mails
):
    _, (appointment,) = await _with_appointment(db_session, admin_user, doctor_user, 5)
    other_day = next(
        d
        for d in ("monday", "tuesday", "wednesday", "thursday", "friday")
        if d != f"{appointment.time_slot.astimezone(SYDNEY):%A}".lower()
    )
    llm.own_appointment = "cancel"

    await _mail(db_session, admin_user, f"cancel my {other_day} appointment", message_id="<own7@x>")

    await db_session.refresh(appointment)
    assert appointment.status != AppointmentStatus.CANCELLED
    ((_, text),) = mails
    assert booking_service.format_slot(appointment.time_slot) in text
    assert "more than one" not in text
    assert "is that the one" in text.lower()


async def test_an_address_that_is_on_no_patient_record_learns_and_cancels_nothing(
    db_session, agent_saver, admin_user, doctor_user, llm, sends, mails
):
    _, (appointment,) = await _with_appointment(db_session, admin_user, doctor_user, 5)
    llm.own_appointment = "cancel"

    await _mail(
        db_session,
        admin_user,
        "cancel Jane Citizen's appointment",
        message_id="<own8@x>",
        sender="someone.else@example.com",
    )

    await db_session.refresh(appointment)
    assert appointment.status != AppointmentStatus.CANCELLED
    assert mails == []
    assert all(booking_service.format_slot(appointment.time_slot) not in text for _, text in sends)


async def test_moving_an_appointment_needs_the_code_then_books_the_new_and_cancels_the_old(
    db_session, agent_saver, admin_user, doctor_user, llm, sends, mails
):
    """A move ran the booking conversation and left the patient with two
    appointments. The conversation remembers which one it replaces, and the
    old one is cancelled only once the new one is booked."""
    _, (old,) = await _with_appointment(db_session, admin_user, doctor_user, 9)
    llm.identity = {"name": "Jane Citizen", "dob": "1990-02-01", "phone": None}
    llm.own_appointment = "move"
    day = _weekday_ahead()
    llm.booking = [{"preferred_day": day.isoformat(), "intent": "change", "confidence": 0.9}]

    email1, _ = await _mail(
        db_session,
        admin_user,
        f"Jane Citizen. I can't make my appointment, can I come on {day:%A} instead?",
        message_id="<m1@example.com>",
    )

    ((to, asked),) = mails
    assert to == SENDER
    assert sends == []  # no times offered before the code comes back
    conversation = await _conversation(db_session, email1.case_id)
    assert conversation.stage == ConversationStage.AWAITING_CONFIRMATION
    assert conversation.appointment_id == old.id

    await _mail(db_session, admin_user, _code(asked), message_id="<m2@example.com>")

    conversation = await _conversation(db_session, email1.case_id)
    assert conversation.stage == ConversationStage.AWAITING_CHOICE
    assert conversation.appointment_id == old.id
    await db_session.refresh(old)
    assert old.status != AppointmentStatus.CANCELLED

    pick = conversation.offered_slots[0]
    llm.booking = [
        {"chosen_time": _local_value(pick["start"]), "intent": "confirm", "confidence": 0.95}
    ]
    await _mail(db_session, admin_user, "The first one please.", message_id="<m3@example.com>")

    await db_session.refresh(old)
    conversation = await _conversation(db_session, email1.case_id)
    assert conversation.stage == ConversationStage.BOOKED
    assert conversation.appointment_id != old.id
    assert old.status == AppointmentStatus.CANCELLED
    text = sends[-1][1]
    assert f"Your earlier appointment on {booking_service.format_slot(old.time_slot)}" in text
    assert "has been cancelled" in text


async def test_a_move_with_two_appointments_goes_to_the_front_desk_and_marks_neither(
    db_session, agent_saver, admin_user, doctor_user, llm, sends, mails
):
    """Live run, 2026-10-11: "anything on Thursday instead?" was read as "my
    Thursday appointment", which was not the one being moved. A day in a move
    is as likely the day they want as the day they have, so with more than one
    appointment a person decides."""
    _, (first, second) = await _with_appointment(db_session, admin_user, doctor_user, 5, 9)
    llm.identity = {"name": "Jane Citizen", "dob": "1990-02-01", "phone": None}
    llm.own_appointment = "move"
    wanted = f"{second.time_slot.astimezone(SYDNEY):%A}"

    email, task = await _mail(
        db_session,
        admin_user,
        f"Jane Citizen. can't make it, anything on {wanted} instead?",
        message_id="<m4@example.com>",
    )

    ((to, text),) = mails
    assert to == SENDER
    assert "front desk will be in touch" in text
    assert booking_service.format_slot(first.time_slot) in text
    conversation = (
        await db_session.execute(
            select(EmailConversation).where(EmailConversation.case_id == email.case_id)
        )
    ).scalar_one_or_none()
    assert conversation is None
    assert [i.notes for i in await _review_items(db_session, task)] == [
        own_appointment_service.MOVE_REASON
    ]


# --- health information sent for a doctor -----------------------------------------

READINGS = "Mon 148/92, Tue 151/95, Fri 162/101. The doctor asked me to send these."


async def test_readings_from_a_known_patient_go_to_their_own_doctor_unanswered(
    db_session, agent_saver, admin_user, doctor_user, llm, sends, mails
):
    """Readings one of which was 162/101 got a generated reply and sat with
    the front desk as answered. Now nothing is generated: the patient's own
    doctor gets a Review Queue item and the patient is told who has it, at
    the address on their record, since that names their doctor."""
    patient = await _registered_patient(db_session, admin_user, doctor_user)
    llm.category = "general_administrative"
    llm.clinical_info = True

    email, task = await _mail(db_session, admin_user, READINGS, message_id="<bp1@example.com>")

    (item,) = await _review_items(db_session, task)
    assert (item.target_role, item.assigned_to) == (UserRole.DOCTOR, doctor_user.id)
    assert item.notes == email_conversation_service.CLINICAL_INFO_REASON
    case = await db_session.get(IntakeCase, email.case_id)
    assert case.patient_id == patient.id
    ((to, text),) = mails
    assert to == SENDER
    assert text == email_conversation_service.clinical_info_text(
        patient.name, doctor_user.full_name
    )
    assert "call 000" in text
    assert sends == []
    assert llm.draft_prompts == []


async def test_readings_from_an_unknown_sender_go_to_the_operator_queue(
    db_session, agent_saver, admin_user, doctor_user, llm, sends, mails
):
    llm.category = "general_administrative"
    llm.clinical_info = True

    _, task = await _mail(
        db_session,
        admin_user,
        READINGS,
        message_id="<bp2@example.com>",
        sender="nobody.we.know@example.com",
    )

    (item,) = await _review_items(db_session, task)
    assert (item.target_role, item.assigned_to) == (UserRole.OPERATOR, None)
    # Names nobody, so an ordinary reply is fine.
    ((_, text),) = sends
    assert text == email_conversation_service.clinical_info_text(None, None)
    assert mails == []


@pytest.mark.parametrize(
    ("intent", "expected"),
    [("general_administrative", "clinical_info"), ("billing_insurance_enquiry", "draft")],
)
def test_only_a_general_email_is_rerouted_as_health_information(intent, expected):
    """The clinical categories already reach a doctor by their own routes."""
    state = {"intent": intent, "identity_outcome": "no_match", "clinical_info": True}

    assert route_identity(state) == expected


def test_a_reply_listing_many_codes_confirms_nothing():
    """A forged reply cannot see the code, but it could list a great many six
    digit numbers and have the right one among them. Only a reply carrying
    exactly one candidate is read as an answer; anything else is a failed
    attempt, and a failed attempt hands the request to the front desk."""
    conversation_id, appointment_id = uuid4(), uuid4()
    right = own_appointment_service.confirmation_code(conversation_id, appointment_id, "cancel")
    other = "000000" if right != "000000" else "111111"

    def read(written: str) -> str | None:
        return own_appointment_service.confirmed_action(written, conversation_id, appointment_id)

    assert read(f"yes please {right}") == "cancel"
    assert read(f"{right} {right}") == "cancel"
    assert read(f"{other} {right}") is None
    assert read(" ".join(f"{n:06d}" for n in range(0, 1000)) + f" {right}") is None


@pytest.mark.parametrize(
    "written",
    ["١٢٣٤٥٦", "１２３４５６", "code: ٤١٥٢٣٣ please", "\x00\udcff 123", ""],
    ids=["arabic-indic", "fullwidth", "mixed", "junk", "empty"],
)
def test_a_reply_in_other_digits_or_junk_is_a_miss_not_a_crash(written):
    """\\d matches every script's digits, and comparing a non-ASCII string in
    constant time raises. A crash would leave the request open, where a miss
    hands it to the front desk."""
    assert own_appointment_service.confirmed_action(written, uuid4(), uuid4()) is None


async def test_a_confirmation_reply_that_cannot_be_read_is_a_miss(
    db_session, agent_saver, admin_user, doctor_user, llm, sends, mails, monkeypatch
):
    """Whatever goes wrong reading the reply, the request is spent and a
    person takes over. Left open, it could be answered again."""
    _, (appointment,) = await _with_appointment(db_session, admin_user, doctor_user, 5)
    llm.own_appointment = "cancel"
    email1, _ = await _mail(
        db_session, admin_user, "pls cancel my appointment", message_id="<own9@x>"
    )
    code = _code(mails[-1][1])

    def boom(*args):
        raise ValueError("unreadable")

    monkeypatch.setattr(own_appointment_service, "confirmed_action", boom)
    _, task = await _mail(db_session, admin_user, code, message_id="<own9b@x>")

    await db_session.refresh(appointment)
    assert appointment.status != AppointmentStatus.CANCELLED
    assert (await _conversation(db_session, email1.case_id)).stage == ConversationStage.STAFF
    assert own_appointment_service.UNCONFIRMED_REASON in [
        i.notes for i in await _review_items(db_session, task)
    ]
