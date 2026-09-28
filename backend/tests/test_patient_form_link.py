"""The registration form link end to end, every flag on.

Inbound mail goes through the real ingest_email and the real graph, as in
test_email_conversation.py. FakeLLM stands in for the model.
"""

import json
import re
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.agents import graph as agent_graph
from app.agents import nodes
from app.agents.graph import route_identity
from app.config import settings
from app.limiter import limiter
from app.models.audit import AuditEvent
from app.models.case import IntakeCase
from app.models.consent import ConsentRecord, ConsentStatus
from app.models.email_conversation import ConversationStage, EmailConversation
from app.models.patient import Patient
from app.routes.public_registration import NOT_VALID
from app.schemas.email import EmailIngestRequest
from app.services import email_conversation_service, email_service, patient_form_service

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


def test_with_the_form_flag_off_routing_is_unchanged(monkeypatch):
    monkeypatch.setattr(settings, "patient_form_link_enabled", False)
    state = {"intent": "appointment_request", "identity_outcome": "no_match", "identity_fields": {}}

    assert route_identity(state) == "conversation"


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
    assert [c["label"] for c in consent.form_snapshot["checks"]] == list(
        patient_form_service.CONSENT_STATEMENTS
    )
    assert all(c["checked"] for c in consent.form_snapshot["checks"])
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
        {"dob": date.today().isoformat()},
        {"dob": (date.today() + timedelta(days=30)).isoformat()},
        {"agree_contact": False},
        {"signature": "data:text/html;base64,PHNjcmlwdD4="},
        {"signature": "data:image/png;base64," + "A" * 200_001},
        {"medicare_number": "1234 56789 1"},
        {"name": ""},
        {"phone": "call me"},
        {"preferred_day": (date.today() + timedelta(days=90)).isoformat()},
    ],
)
async def test_a_bad_form_is_refused_and_the_link_stays_open(
    client, db_session, admin_user, llm, sends, overrides
):
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
