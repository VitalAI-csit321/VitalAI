"""The email conversation flow (email_conversation_service), flag on.

Every turn goes through the real ingest_email (so reply linking is exercised)
and the real graph. The model is FakeLLM: tests decide what it "read", and the
code under test decides what that is allowed to mean.
"""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.agents import graph as agent_graph
from app.agents.graph import route_identity
from app.config import settings
from app.models.appointment import Appointment
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
from app.schemas.call import CallRouteRequest
from app.schemas.email import EmailIngestRequest
from app.services import (
    appointment_service,
    call_service,
    email_conversation_service,
    email_service,
    identity_service,
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
    assert len(sends) == sent_before


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
