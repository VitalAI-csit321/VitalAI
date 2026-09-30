"""The registration form link end to end, every flag on.

Inbound mail goes through the real ingest_email and the real graph, as in
test_email_conversation.py. FakeLLM stands in for the model.
"""

import json
import re
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import select

from app.agents import graph as agent_graph
from app.agents import nodes
from app.agents.graph import route_identity
from app.config import settings
from app.limiter import limiter
from app.models.appointment import Appointment
from app.models.audit import AuditEvent
from app.models.case import IntakeCase
from app.models.consent import ConsentRecord, ConsentStatus
from app.models.email_conversation import ConversationStage, EmailConversation
from app.models.patient import Patient
from app.models.task import TaskItemStatus
from app.routes.public_registration import NOT_VALID
from app.schemas.email import EmailIngestRequest
from app.services import (
    consent_service,
    email_conversation_service,
    email_service,
    patient_form_service,
)

SYDNEY = ZoneInfo("Australia/Sydney")
SENDER = "jane@example.com"
URL = "/api/v1/public/registration"
LINK = re.compile(r"/register/([A-Za-z0-9_-]+)")
SIGNATURE = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGD4DwABBAEAwS2OUAAAAABJRU5ErkJggg=="


@pytest.fixture(autouse=True)
def flags(monkeypatch):
    for flag in (
        "agentic_pipeline_enabled",
        "email_booking_conversation_enabled",
        "patient_form_link_enabled",
    ):
        monkeypatch.setattr(settings, flag, True)
    monkeypatch.setattr(settings, "clinic_open_hour", 8)
    monkeypatch.setattr(settings, "clinic_close_hour", 18)
    monkeypatch.setattr(settings, "clinic_timezone", "Australia/Sydney")
    monkeypatch.setattr(settings, "default_appointment_duration_minutes", 30)
    monkeypatch.setattr(settings, "cors_origins", "https://app.clinic.example")
    limiter.reset()


@pytest.fixture
def llm(monkeypatch):
    from tests.agent_fakes import FakeLLM

    fake = FakeLLM(category="appointment_request", confidence=0.95)
    monkeypatch.setattr("app.services.email_service.get_llm", lambda: fake)
    return fake


@pytest.fixture
def sends(monkeypatch):
    """Every reply that would have reached Graph, in order: (message_id, text)."""
    monkeypatch.setattr(settings, "outlook_enabled", True)
    monkeypatch.setattr("app.services.outlook_auth.get_access_token", AsyncMock(return_value="t"))
    sent: list[tuple[str, str]] = []

    async def send_reply(token, message_id, body):
        sent.append((message_id, body))

    monkeypatch.setattr("app.services.outlook_client.send_reply", send_reply)
    return sent


def _weekday_ahead(days: int = 3) -> date:
    day = datetime.now(SYDNEY).date() + timedelta(days=days)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


async def _mail(db, actor, body, *, message_id, references=None, sender=SENDER, **extra):
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
    # Ends the savepoint ingest_email's refresh opened, which the graph's own
    # sessions nested inside. Left open, a route that rolls back (a refused
    # form) would undo the graph's rows too, which cannot happen outside tests.
    await db.commit()
    await db.refresh(task)
    return email, task


async def _link_sent(db, admin, llm, sends, *, category="appointment_request"):
    """The first email from an unknown sender, and the token it was sent."""
    llm.category = category
    email, task = await _mail(
        db, admin, "Hi, can I get an appointment please?", message_id="<f1@example.com>"
    )
    return email, task, LINK.search(sends[-1][1]).group(1)


async def _conversation(db, case_id) -> EmailConversation:
    row = (
        await db.execute(select(EmailConversation).where(EmailConversation.case_id == case_id))
    ).scalar_one()
    await db.refresh(row)
    return row


# --- routing -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("intent", "outcome", "expected"),
    [
        ("appointment_request", "no_match", "form_link"),
        ("new_patient_onboarding", "no_match", "form_link"),
        ("appointment_request", "matched", "conversation"),
        ("appointment_request", "ambiguous", "request_verification"),
        ("medical_records_request", "no_match", "request_verification"),
    ],
)
def test_only_unknown_bookers_and_sign_ups_are_sent_the_form(intent, outcome, expected):
    state = {"intent": intent, "identity_outcome": outcome, "identity_fields": {}}

    assert route_identity(state) == expected


@pytest.mark.parametrize(
    ("intent", "fields", "expected"),
    [
        ("appointment_request", {}, "conversation"),
        ("new_patient_onboarding", {}, "request_verification"),
        ("new_patient_onboarding", {"name": "Jane Citizen"}, "onboarding"),
    ],
)
def test_with_the_form_flag_off_routing_is_unchanged(monkeypatch, intent, fields, expected):
    monkeypatch.setattr(settings, "patient_form_link_enabled", False)
    state = {"intent": intent, "identity_outcome": "no_match", "identity_fields": fields}

    assert route_identity(state) == expected


# --- the link email ----------------------------------------------------------------


async def test_an_unknown_booker_gets_the_link_and_no_patient_yet(
    db_session, agent_saver, admin_user, llm, sends
):
    email, task, token = await _link_sent(db_session, admin_user, llm, sends)

    ((message_id, text),) = sends
    assert message_id == email.external_id
    assert f"https://app.clinic.example/register/{token}" in text
    case = await db_session.get(IntakeCase, email.case_id)
    assert case.patient_id is None
    patients = (
        (await db_session.execute(select(Patient).where(Patient.email == SENDER))).scalars().all()
    )
    assert patients == []
    conversation = await _conversation(db_session, email.case_id)
    assert conversation.stage == ConversationStage.AWAITING_DETAILS
    assert conversation.form_token_hash == patient_form_service.token_hash(token)
    assert conversation.form_sent_at is not None
    assert conversation.last_outbound_text == text
    assert task.draft_sent is True
    assert task.handover_context == patient_form_service.WAITING_REASON
    issued = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "agent.form_link_issued")
            )
        )
        .scalars()
        .all()
    )
    assert len(issued) == 1
    assert token not in json.dumps(issued[0].details)


async def test_a_sign_up_request_gets_the_same_link(
    db_session, agent_saver, admin_user, llm, sends
):
    await _link_sent(db_session, admin_user, llm, sends, category="new_patient_onboarding")

    assert LINK.search(sends[-1][1])


async def test_an_automatic_message_gets_no_link(db_session, agent_saver, admin_user, llm, sends):
    email, task = await _mail(
        db_session,
        admin_user,
        "I am out of the office until Monday.",
        message_id="<ooo@example.com>",
        auto_submitted=True,
    )

    assert sends == []
    assert task.handover_context == nodes._AUTOMATIC_REASON


async def test_with_auto_send_off_the_link_waits_for_approval_and_opens_once_sent(
    db_session, agent_saver, admin_user, llm, sends, monkeypatch
):
    monkeypatch.setattr(settings, "email_auto_send_enabled", False)
    email, _ = await _mail(
        db_session, admin_user, "Can I book in please?", message_id="<ap@example.com>"
    )

    assert sends == []
    conversation = await _conversation(db_session, email.case_id)
    assert conversation.form_token_hash is not None
    assert conversation.form_sent_at is None


# --- the form ----------------------------------------------------------------------


def _form(day: date | None, **overrides) -> dict:
    body = {
        "name": "Jane Citizen",
        "dob": "1990-02-01",
        "phone": "0412 345 678",
        "address": "1 Test Street",
        "preferred_language": "",
        "preferred_day": day.isoformat() if day else "",
        "part_of_day": "any",
        "agree_data": True,
        "agree_contact": True,
        "signature": SIGNATURE,
    }
    return body | overrides


async def test_the_link_opens_with_the_address_and_the_statements(
    client, db_session, admin_user, llm, sends
):
    await _link_sent(db_session, admin_user, llm, sends)
    token = LINK.search(sends[-1][1]).group(1)

    response = await client.get(f"{URL}/{token}")

    assert response.status_code == 200
    assert response.json() == {
        "email": SENDER,
        "needs_preferred_day": True,
        "statements": list(patient_form_service.CONSENT_STATEMENTS),
        # The clinic's own consent, the one staff capture in person.
        "clauses": list(consent_service.CLINIC_CLAUSES),
        "clinic_checks": list(consent_service.CLINIC_CHECKS),
        "doctors": [],  # no doctor in this test's clinic
    }


async def test_a_bad_link_and_a_disabled_feature_look_the_same(
    client, db_session, admin_user, llm, sends, monkeypatch
):
    _, _, token = await _link_sent(db_session, admin_user, llm, sends)

    unknown = await client.get(f"{URL}/not-a-real-token")
    monkeypatch.setattr(settings, "patient_form_link_enabled", False)
    disabled = await client.get(f"{URL}/{token}")

    for response in (unknown, disabled):
        assert response.status_code == 404
        assert response.json() == {"detail": NOT_VALID}


async def test_submitting_creates_the_record_and_one_pending_consent(
    client, db_session, admin_user, doctor_user, llm, sends
):
    email, task, token = await _link_sent(db_session, admin_user, llm, sends)
    day = _weekday_ahead()

    response = await client.post(f"{URL}/{token}", json=_form(day))

    assert response.status_code == 201
    case = await db_session.get(IntakeCase, email.case_id)
    await db_session.refresh(case)
    patient = await db_session.get(Patient, case.patient_id)
    assert patient.is_provisional
    assert (patient.name, patient.dob, patient.phone, patient.email) == (
        "Jane Citizen",
        date(1990, 2, 1),
        "0412 345 678",
        SENDER,
    )
    assert patient.address == "1 Test Street"
    assert patient.preferred_language is None
    conversation = await _conversation(db_session, email.case_id)
    assert conversation.patient_id == patient.id
    assert conversation.preferred_day == day
    assert conversation.form_submitted_at is not None
    consents = (
        (await db_session.execute(select(ConsentRecord).where(ConsentRecord.case_id == case.id)))
        .scalars()
        .all()
    )
    (consent,) = consents
    assert consent.consent_type == "online_registration"
    assert consent.status == ConsentStatus.PENDING
    assert consent.form_snapshot["signature"] == SIGNATURE
    assert [c["label"] for c in consent.form_snapshot["checks"]] == [
        *patient_form_service.CONSENT_STATEMENTS,
        *consent_service.CLINIC_CHECKS,
    ]
    # The two registration statements are required; the clinic's are not.
    assert [c["checked"] for c in consent.form_snapshot["checks"]] == [True, True] + [False] * 4
    (event,) = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "patient.form_submitted")
            )
        )
        .scalars()
        .all()
    )
    details = json.dumps(event.details)
    for value in ("Jane", "Citizen", "Test Street", SIGNATURE[:30]):
        assert value not in details
    assert event.details["outcome"] == "created"
    assert event.details["fields"] == [
        "address",
        "dob",
        "name",
        "part_of_day",
        "phone",
        "preferred_day",
    ]


async def test_a_link_works_once(client, db_session, admin_user, doctor_user, llm, sends):
    _, _, token = await _link_sent(db_session, admin_user, llm, sends)

    first = await client.post(f"{URL}/{token}", json=_form(_weekday_ahead()))
    second = await client.post(f"{URL}/{token}", json=_form(_weekday_ahead()))

    assert first.status_code == 201
    assert second.status_code == 404
    assert (await client.get(f"{URL}/{token}")).status_code == 404


@pytest.mark.parametrize(
    "overrides",
    [
        {"preferred_day": ""},  # a booking needs a day
        # Days from today as callables: parametrize runs at collection, and a
        # run that crosses midnight would turn "today" into yesterday.
        {"dob": lambda: date.today().isoformat()},
        {"dob": lambda: (date.today() + timedelta(days=30)).isoformat()},
        {"agree_contact": False},
        {"signature": "data:text/html;base64,PHNjcmlwdD4="},
        {"signature": "data:image/png;base64," + "A" * 200_001},
        {"medicare_number": "1234 56789 1"},
        {"name": ""},
        {"phone": "call me"},
        {"phone": "(((((("},  # no digits: identity could never match it
        {"clinic_checks": [True]},  # one answer per clinic statement, or none
        {"name": "Jane\x00Citizen"},
        {"address": "1 Test Street\x07"},
        {"preferred_day": lambda: (date.today() + timedelta(days=90)).isoformat()},
    ],
)
async def test_a_bad_form_is_refused_and_the_link_stays_open(
    client, db_session, admin_user, llm, sends, overrides
):
    overrides = {k: v() if callable(v) else v for k, v in overrides.items()}
    email, _, token = await _link_sent(db_session, admin_user, llm, sends)
    # Read now: the route's rollback on a refused form expires every object in
    # the session the test shares with it.
    case_id = email.case_id

    response = await client.post(f"{URL}/{token}", json=_form(_weekday_ahead(), **overrides))

    assert response.status_code == 422
    case = await db_session.get(IntakeCase, case_id)
    await db_session.refresh(case)
    assert case.patient_id is None
    assert (await client.get(f"{URL}/{token}")).status_code == 200


async def test_details_matching_one_registered_patient_link_to_them_and_change_nothing(
    client, db_session, admin_user, doctor_user, llm, sends
):
    email, _, token = await _link_sent(db_session, admin_user, llm, sends)
    existing = Patient(
        mrn="MRN-EXIST01",
        name="Jane Citizen",
        dob=date(1990, 2, 1),
        phone="+61 412 345 678",
        email="jane.old@example.com",
        is_provisional=False,
    )
    db_session.add(existing)
    await db_session.commit()

    response = await client.post(f"{URL}/{token}", json=_form(_weekday_ahead()))

    assert response.status_code == 201
    await db_session.refresh(existing)
    assert existing.email == "jane.old@example.com"
    assert existing.address is None
    conversation = await _conversation(db_session, email.case_id)
    assert conversation.patient_id == existing.id
    count = (
        (await db_session.execute(select(Patient).where(Patient.name == "Jane Citizen")))
        .scalars()
        .all()
    )
    assert len(count) == 1


async def test_a_registered_patient_booking_by_form_joins_a_case(
    client, db_session, admin_user, doctor_user, llm, sends
):
    from app.models.case import IntakeCase
    from app.models.episode import Episode

    email, _, token = await _link_sent(db_session, admin_user, llm, sends)
    existing = Patient(
        mrn="MRN-EXIST02",
        name="Jane Citizen",
        dob=date(1990, 2, 1),
        phone="+61 412 345 678",
        is_provisional=False,
    )
    db_session.add(existing)
    await db_session.commit()

    response = await client.post(f"{URL}/{token}", json=_form(_weekday_ahead()))

    assert response.status_code == 201
    (episode,) = (await db_session.scalars(select(Episode))).all()
    contact = await db_session.get(IntakeCase, email.case_id)
    await db_session.refresh(contact)
    assert (episode.patient_id, contact.episode_id) == (existing.id, episode.id)


async def test_details_partly_matching_someone_go_to_staff_quietly(
    client, db_session, admin_user, doctor_user, llm, sends
):
    email, task, token = await _link_sent(db_session, admin_user, llm, sends)
    db_session.add(
        Patient(mrn="MRN-OTHER01", name="Sam Other", phone="0412 345 678", is_provisional=False)
    )
    await db_session.commit()

    response = await client.post(f"{URL}/{token}", json=_form(_weekday_ahead()))

    assert response.status_code == 201
    case = await db_session.get(IntakeCase, email.case_id)
    await db_session.refresh(case)
    assert case.patient_id is None
    conversation = await _conversation(db_session, email.case_id)
    assert conversation.stage == ConversationStage.STAFF
    await db_session.refresh(task)
    assert task.handover_context.startswith(email_conversation_service.STAFF_REASONS["ambiguous"])
    assert "Jane Citizen" in task.handover_context
    assert len(sends) == 1  # the link only; no follow-up


async def test_a_link_used_after_an_email_reply_fills_that_record_not_a_new_one(
    client, db_session, admin_user, doctor_user, llm, sends
):
    email, _, token = await _link_sent(db_session, admin_user, llm, sends)
    # The patient answers by email instead, with details but no day.
    llm.booking = [
        {"name": "Jane Citizen", "dob": "1990-02-01", "intent": "unclear", "confidence": 0.9}
    ]
    await _mail(
        db_session,
        admin_user,
        "Jane Citizen, born 1/2/1990",
        message_id="<f2@example.com>",
        references="<f1@example.com>",
    )
    conversation = await _conversation(db_session, email.case_id)
    first_record = conversation.patient_id
    assert first_record is not None

    response = await client.post(f"{URL}/{token}", json=_form(_weekday_ahead()))

    assert response.status_code == 201
    conversation = await _conversation(db_session, email.case_id)
    assert conversation.patient_id == first_record
    patient = await db_session.get(Patient, first_record)
    await db_session.refresh(patient)
    assert patient.phone == "0412 345 678"
    same_name = (
        (await db_session.execute(select(Patient).where(Patient.name == "Jane Citizen")))
        .scalars()
        .all()
    )
    assert len(same_name) == 1


async def test_the_public_endpoints_are_rate_limited(client):
    statuses = [(await client.get(f"{URL}/guess-{i}")).status_code for i in range(11)]

    assert statuses[:10] == [404] * 10
    assert statuses[10] == 429


# --- the follow-up and the booking --------------------------------------------------


@pytest.fixture(autouse=True)
def followups(monkeypatch, detached_sessionmaker):
    """send_followup opens its own session, as it does in production. Autouse:
    every successful submit in this file, Task 3's tests included, schedules it."""
    monkeypatch.setattr(patient_form_service, "AsyncSessionLocal", detached_sessionmaker)


async def _submitted(client, db, admin, llm, sends, day, **form):
    email, task, token = await _link_sent(db, admin, llm, sends)
    response = await client.post(f"{URL}/{token}", json=_form(day, **form))
    assert response.status_code == 201
    await db.refresh(task)
    return email, task


async def test_the_follow_up_gives_the_mrn_and_the_free_times(
    client, db_session, admin_user, doctor_user, llm, sends, followups
):
    day = _weekday_ahead()
    email, task = await _submitted(client, db_session, admin_user, llm, sends, day)

    assert len(sends) == 2
    message_id, text = sends[1]
    assert message_id == email.external_id  # a reply in the original thread
    conversation = await _conversation(db_session, email.case_id)
    patient = await db_session.get(Patient, conversation.patient_id)
    assert f"Your reference number (MRN) is {patient.mrn}" in text
    assert "These times are available on" in text
    assert "Nothing has been booked yet" in text
    assert "By confirming a time you agree" in text
    assert conversation.stage == ConversationStage.AWAITING_CHOICE
    assert conversation.offered_slots
    assert conversation.last_outbound_text == text
    assert task.handover_context == patient_form_service.OFFERED_REASON


async def test_a_weekend_day_is_offered_the_nearest_weekdays(
    client, db_session, admin_user, doctor_user, llm, sends, followups
):
    saturday = _weekday_ahead()
    while saturday.weekday() != 5:
        saturday += timedelta(days=1)

    email, _ = await _submitted(client, db_session, admin_user, llm, sends, saturday)

    assert "We have nothing free on" in sends[1][1]
    conversation = await _conversation(db_session, email.case_id)
    assert conversation.stage == ConversationStage.AWAITING_CHOICE


async def test_a_sign_up_without_a_day_gets_the_mrn_and_is_asked_for_one(
    client, db_session, admin_user, doctor_user, llm, sends, followups
):
    email, task, token = await _link_sent(
        db_session, admin_user, llm, sends, category="new_patient_onboarding"
    )
    assert (await client.get(f"{URL}/{token}")).json()["needs_preferred_day"] is False

    response = await client.post(f"{URL}/{token}", json=_form(None))

    assert response.status_code == 201
    text = sends[1][1]
    assert "MRN" in text
    assert "reply to this email with the day you would prefer" in text
    conversation = await _conversation(db_session, email.case_id)
    assert conversation.stage == ConversationStage.AWAITING_DETAILS
    assert conversation.offered_slots == []


async def test_no_free_time_tells_the_patient_and_hands_to_staff(
    client, db_session, admin_user, llm, sends, followups
):
    # No doctor exists, so nothing is free anywhere.
    email, task = await _submitted(client, db_session, admin_user, llm, sends, _weekday_ahead())

    assert "A member of our team will be in touch" in sends[1][1]
    conversation = await _conversation(db_session, email.case_id)
    assert conversation.stage == ConversationStage.STAFF
    assert task.handover_context == email_conversation_service.STAFF_REASONS["no_slots"]


async def test_a_failed_follow_up_keeps_the_registration_and_tells_staff(
    client, db_session, admin_user, doctor_user, llm, sends, followups, monkeypatch
):
    email, task, token = await _link_sent(db_session, admin_user, llm, sends)

    async def refused(token, message_id, body):
        raise httpx.HTTPError("mailbox unavailable")

    monkeypatch.setattr("app.services.outlook_client.send_reply", refused)
    response = await client.post(f"{URL}/{token}", json=_form(_weekday_ahead()))

    assert response.status_code == 201
    conversation = await _conversation(db_session, email.case_id)
    assert conversation.patient_id is not None
    assert conversation.offered_slots == []
    await db_session.refresh(task)
    assert task.handover_context == patient_form_service.FOLLOWUP_FAILED_REASON
    (failed,) = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "patient.form_followup_failed")
            )
        )
        .scalars()
        .all()
    )
    assert failed.details["error"] == "EmailSendError"
    assert SENDER not in json.dumps(failed.details)


async def test_a_follow_up_the_critic_rejects_is_not_sent_and_staff_are_told(
    client, db_session, admin_user, doctor_user, llm, sends, followups, monkeypatch
):
    email, task, token = await _link_sent(db_session, admin_user, llm, sends)
    monkeypatch.setattr(patient_form_service, "critique", lambda text, branch=None: "no")

    response = await client.post(f"{URL}/{token}", json=_form(_weekday_ahead()))

    assert response.status_code == 201
    assert len(sends) == 1  # the link only
    await db_session.refresh(task)
    assert task.handover_context == patient_form_service.FOLLOWUP_FAILED_REASON
    (failed,) = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "patient.form_followup_failed")
            )
        )
        .scalars()
        .all()
    )
    assert failed.details["error"] == "blocked"


async def test_until_the_follow_up_goes_the_task_says_it_is_on_its_way(
    client, db_session, admin_user, doctor_user, llm, sends, monkeypatch
):
    # A follow-up lost to a restart must not look like normal progress.
    email, task, token = await _link_sent(db_session, admin_user, llm, sends)
    monkeypatch.setattr(patient_form_service, "send_followup", AsyncMock())

    assert (await client.post(f"{URL}/{token}", json=_form(_weekday_ahead()))).status_code == 201

    await db_session.refresh(task)
    assert task.handover_context == patient_form_service.FOLLOWUP_PENDING_REASON


async def test_a_refused_phone_says_why_in_plain_words(client, db_session, admin_user, llm, sends):
    _, _, token = await _link_sent(db_session, admin_user, llm, sends)

    response = await client.post(f"{URL}/{token}", json=_form(_weekday_ahead(), phone="call me"))

    assert response.status_code == 422
    assert [e["msg"] for e in response.json()["detail"]] == [
        "Please enter a phone number with at least 6 digits."
    ]


@pytest.mark.parametrize("references", ["<f1@example.com>", None])
async def test_replying_with_an_offered_time_books_it(
    client, db_session, admin_user, doctor_user, llm, sends, followups, references
):
    # references=None: webmail that drops threading headers; the address
    # fallback must still find the conversation.
    email, _ = await _submitted(client, db_session, admin_user, llm, sends, _weekday_ahead())
    conversation = await _conversation(db_session, email.case_id)
    pick = conversation.offered_slots[0]
    llm.booking = [{"intent": "confirm", "confidence": 0.95}]

    await _mail(
        db_session,
        admin_user,
        "The first one please",
        message_id="<f3@example.com>",
        references=references,
    )

    appointment = (
        await db_session.execute(select(Appointment).where(Appointment.case_id == email.case_id))
    ).scalar_one()
    assert str(appointment.doctor_id) == pick["doctor_id"]
    assert appointment.appointment_type == "new_patient"
    conversation = await _conversation(db_session, email.case_id)
    assert conversation.stage == ConversationStage.BOOKED
    assert "Your appointment is booked for" in sends[-1][1]


# --- after the form: what staff see, and what later emails do ------------------------


async def test_an_email_after_the_form_went_to_staff_gets_no_second_link(
    client, db_session, admin_user, doctor_user, llm, sends
):
    email, _, token = await _link_sent(db_session, admin_user, llm, sends)
    case_id = email.case_id
    db_session.add(
        Patient(mrn="MRN-OTHER02", name="Sam Other", phone="0412 345 678", is_provisional=False)
    )
    await db_session.commit()
    assert (await client.post(f"{URL}/{token}", json=_form(_weekday_ahead()))).status_code == 201

    _, later = await _mail(
        db_session,
        admin_user,
        "Any news on my registration?",
        message_id="<f4@example.com>",
        references="<f1@example.com>",
    )

    assert len(sends) == 1  # the first link only
    conversation = await _conversation(db_session, case_id)
    assert conversation.stage == ConversationStage.STAFF
    assert later.handover_context == email_conversation_service.STAFF_REASONS["closed"]


async def test_a_hand_off_to_staff_reopens_an_archived_task(
    client, db_session, admin_user, llm, sends
):
    # No doctor exists, so the follow-up finds no free time and hands to staff.
    email, task, token = await _link_sent(db_session, admin_user, llm, sends)
    task.status = TaskItemStatus.COMPLETED
    task.read_at = datetime.now(UTC)
    task.deleted_at = datetime.now(UTC)
    task.deleted_by = admin_user.id
    await db_session.commit()

    assert (await client.post(f"{URL}/{token}", json=_form(_weekday_ahead()))).status_code == 201

    await db_session.refresh(task)
    assert task.handover_context == email_conversation_service.STAFF_REASONS["no_slots"]
    assert task.status == TaskItemStatus.PENDING
    assert task.read_at is None
    assert task.deleted_at is None and task.deleted_by is None


async def test_form_details_contradicting_the_emailed_ones_go_to_staff(
    client, db_session, admin_user, doctor_user, llm, sends
):
    email, task, token = await _link_sent(db_session, admin_user, llm, sends)
    llm.booking = [
        {"name": "Jane Citizen", "dob": "1990-02-01", "intent": "unclear", "confidence": 0.9}
    ]
    await _mail(
        db_session,
        admin_user,
        "Jane Citizen, born 1/2/1990",
        message_id="<f2@example.com>",
        references="<f1@example.com>",
    )
    case_id = email.case_id
    sent_before = len(sends)

    response = await client.post(f"{URL}/{token}", json=_form(_weekday_ahead(), dob="1991-03-04"))

    assert response.status_code == 201
    assert len(sends) == sent_before  # no follow-up
    conversation = await _conversation(db_session, case_id)
    assert conversation.stage == ConversationStage.STAFF
    patient = await db_session.get(Patient, conversation.patient_id)
    await db_session.refresh(patient)
    assert patient.dob == date(1990, 2, 1)  # nothing overwritten
    await db_session.refresh(task)
    assert task.handover_context.startswith(patient_form_service.MISMATCH_REASON)
    assert "04/03/1991" in task.handover_context


async def test_a_reply_with_no_details_while_the_link_is_open_sends_nothing(
    client, db_session, admin_user, llm, sends
):
    email, _, token = await _link_sent(db_session, admin_user, llm, sends)
    llm.booking = [
        {"intent": "unclear", "confidence": 0.9},
        {"intent": "unclear", "confidence": 0.3},
    ]

    for i, body in enumerate(("Thanks, I will fill it in tonight", "ok")):
        _, reply_task = await _mail(
            db_session,
            admin_user,
            body,
            message_id=f"<t{i}@example.com>",
            references="<f1@example.com>",
        )
        assert (
            reply_task.handover_context
            == (email_conversation_service.STAFF_REASONS["form_pending"])
        )

    assert len(sends) == 1
    conversation = await _conversation(db_session, email.case_id)
    assert conversation.stage == ConversationStage.AWAITING_DETAILS
    assert (await client.get(f"{URL}/{token}")).status_code == 200


async def test_the_clinic_consent_can_be_left_part_done_and_unsigned(
    client, db_session, admin_user, doctor_user, llm, sends
):
    email, _, token = await _link_sent(db_session, admin_user, llm, sends)
    case_id = email.case_id

    response = await client.post(
        f"{URL}/{token}",
        json=_form(_weekday_ahead(), clinic_checks=[True, False, True, False], signature=""),
    )

    assert response.status_code == 201
    (consent,) = (
        (await db_session.execute(select(ConsentRecord).where(ConsentRecord.case_id == case_id)))
        .scalars()
        .all()
    )
    assert consent.status == ConsentStatus.PENDING  # completed at the clinic
    assert consent.form_snapshot["signature"] is None
    assert [c["checked"] for c in consent.form_snapshot["checks"]] == [
        True,
        True,
        True,
        False,
        True,
        False,
    ]


# The preferred doctor on the form (M4 spec, E6)


async def _gone_doctor(db):
    from app.models.user import User, UserRole

    gone = User(
        email="gone.doctor@example.com",
        hashed_password="h",
        full_name="Dr Gone",
        role=UserRole.DOCTOR,
        is_active=False,
    )
    db.add(gone)
    await db.commit()
    return gone


async def test_the_form_lists_only_active_doctors_by_name(
    client, db_session, admin_user, doctor_user, llm, sends
):
    _, _, token = await _link_sent(db_session, admin_user, llm, sends)
    await _gone_doctor(db_session)

    doctors = (await client.get(f"{URL}/{token}")).json()["doctors"]

    assert doctors == [{"id": str(doctor_user.id), "name": doctor_user.full_name}]


async def test_a_preferred_doctor_on_the_form_waits_for_registration(
    client, db_session, admin_user, doctor_user, llm, sends
):
    from app.models.assignment import DoctorPatientAssignment

    email, _, token = await _link_sent(db_session, admin_user, llm, sends)

    response = await client.post(
        f"{URL}/{token}",
        json=_form(_weekday_ahead(), preferred_doctor_id=str(doctor_user.id)),
    )

    assert response.status_code == 201
    conversation = await _conversation(db_session, email.case_id)
    patient = await db_session.get(Patient, conversation.patient_id)
    await db_session.refresh(patient)
    assert patient.is_provisional and patient.preferred_doctor_id == doctor_user.id
    # Provisional: no doctor until staff register them (E6).
    rows = await db_session.scalars(
        select(DoctorPatientAssignment).where(DoctorPatientAssignment.patient_id == patient.id)
    )
    assert rows.all() == []


async def test_an_inactive_preferred_doctor_is_refused_on_the_form(
    client, db_session, admin_user, llm, sends
):
    _, _, token = await _link_sent(db_session, admin_user, llm, sends)
    gone = await _gone_doctor(db_session)
    response = await client.post(
        f"{URL}/{token}", json=_form(_weekday_ahead(), preferred_doctor_id=str(gone.id))
    )
    assert response.status_code == 422
