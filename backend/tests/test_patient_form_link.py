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
from app.models.email_conversation import ConversationStage, EmailConversation
from app.models.patient import Patient
from app.schemas.email import EmailIngestRequest
from app.services import email_service, patient_form_service

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
