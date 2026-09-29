"""One send path for every outbound reply (build spec §4, Appendix F.12/F.14).

Auto-send used to persist draft_sent=True and stop, so an "auto-sent" reply
was recorded and shown as sent but never left the system. Both the approvals
executor and the auto-send branch now go through email_service.deliver_reply.
"""

import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select

from app.models.approval import ApprovalRequest
from app.models.audit import AuditEvent
from app.schemas.email import EmailIngestRequest
from app.services import email_service
from app.services.outlook_auth import OutlookAuthRequiredError


class _FakeLLM:
    def __init__(self, response: str):
        self.response = response

    async def ainvoke(self, prompt: str) -> str:
        if "worthy" in prompt.lower():
            return json.dumps({"worthy": True, "reason": "test default"})
        return self.response


async def _auto_sendable(db_session, actor, monkeypatch):
    """An email that passes every auto-send condition, from a real mailbox."""
    monkeypatch.setattr(email_service.settings, "outlook_enabled", True)
    monkeypatch.setattr(
        "app.services.email_service.get_llm",
        lambda: _FakeLLM(json.dumps({"category": "general_administrative", "confidence": 0.95})),
    )
    monkeypatch.setattr("app.services.outlook_auth.get_access_token", AsyncMock(return_value="t"))
    return await email_service.ingest_email(
        db_session,
        EmailIngestRequest(
            sender="patient@example.com",
            recipient="clinic@example.com",
            subject="Opening hours",
            body="What time do you open on Saturdays?",
            external_id="AAMk-auto",
            external_source="outlook",
        ),
        actor,
    )


async def _draft(db_session, task, email, actor, gate, confidence):
    with patch(
        "app.services.email_service._generate_org_grounded_reply",
        new=AsyncMock(return_value=("We open at 9am on Saturdays.", True)),
    ):
        return await email_service.draft_reply(db_session, task, email, actor, gate, confidence)


async def _approvals_for(db_session, task) -> list[ApprovalRequest]:
    rows = (await db_session.execute(select(ApprovalRequest))).scalars().all()
    return [r for r in rows if r.payload.get("task_id") == str(task.id)]


@pytest.mark.asyncio
async def test_auto_send_delivers_once_and_marks_sent_only_afterwards(
    db_session, front_desk_user, monkeypatch
):
    email, task, gate, confidence = await _auto_sendable(db_session, front_desk_user, monkeypatch)
    sends = []

    async def fake_send(token, message_id, body):
        # draft_sent must not already claim delivery while the send is in flight.
        sends.append((message_id, body, task.draft_sent))

    monkeypatch.setattr("app.services.outlook_client.send_reply", fake_send)

    outcome = await _draft(db_session, task, email, front_desk_user, gate, confidence)

    assert sends == [("AAMk-auto", "We open at 9am on Saturdays.", False)]
    assert outcome.sent is True
    assert outcome.approval_id is None
    await db_session.refresh(task)
    assert task.draft_sent is True
    assert await _approvals_for(db_session, task) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        httpx.HTTPStatusError(
            "403", request=httpx.Request("POST", "https://graph"), response=httpx.Response(403)
        ),
        OutlookAuthRequiredError("nobody signed in"),
    ],
    ids=["send_error", "auth_required"],
)
async def test_failed_auto_send_falls_back_to_the_approval_queue(
    db_session, front_desk_user, monkeypatch, failure
):
    email, task, gate, confidence = await _auto_sendable(db_session, front_desk_user, monkeypatch)
    monkeypatch.setattr("app.services.outlook_client.send_reply", AsyncMock(side_effect=failure))
    if isinstance(failure, OutlookAuthRequiredError):
        monkeypatch.setattr(
            "app.services.outlook_auth.get_access_token", AsyncMock(side_effect=failure)
        )

    outcome = await _draft(db_session, task, email, front_desk_user, gate, confidence)

    assert outcome.sent is False
    assert outcome.approval_id is not None
    await db_session.refresh(task)
    assert task.draft_sent is False
    assert str(task.draft_approval_id) == outcome.approval_id
    (approval,) = await _approvals_for(db_session, task)
    assert approval.payload["draft"] == "We open at 9am on Saturdays."
    assert approval.payload["delivery_error"]


def _callers_of(function: str) -> list[str]:
    app_dir = Path(__file__).resolve().parent.parent / "app"
    return [
        str(p.relative_to(app_dir))
        for p in app_dir.rglob("*.py")
        for _ in re.finditer(rf"outlook_client\.{function}\(", p.read_text())
    ]


def test_outlook_send_reply_has_exactly_one_caller_in_app():
    """Every outbound reply goes through deliver_reply. A second caller would
    be a send path without P1's draft_sent guard."""
    assert _callers_of("send_reply") == ["services/email_service.py"]


def test_outlook_send_mail_has_exactly_one_caller_in_app():
    """Every new outbound message goes through deliver_new_message (spec
    §16.1). This one matters more than send_reply's: appointment reminders
    are the only feature that mails a patient with nobody approving it, so a
    second caller would be an unapproved send path with no audit event and no
    idempotency guard behind it."""
    assert _callers_of("send_mail") == ["services/email_service.py"]


async def _reminder_events(db_session, actor) -> list:
    """Scoped to this actor: the AGENT_XPROC worker commits audit rows a
    trigger makes undeletable, so a global count passes alone and fails in a
    full run."""
    rows = (await db_session.execute(select(AuditEvent))).scalars().all()
    return [e for e in rows if e.action == "test.new_message" and e.actor_id == actor.id]


@pytest.mark.asyncio
async def test_deliver_new_message_simulates_the_send_with_the_connector_off(
    db_session, front_desk_user, monkeypatch
):
    """Tests never need a mailbox: with outlook_enabled False the send is
    recorded at DB level and no message leaves the system."""
    monkeypatch.setattr(email_service.settings, "outlook_enabled", False)
    sends = AsyncMock()
    monkeypatch.setattr("app.services.outlook_client.send_mail", sends)

    await email_service.deliver_new_message(
        db_session,
        to_address="someone@example.com",
        subject="Subject",
        body="Body",
        actor=front_desk_user,
        case_id=None,
        action="test.new_message",
        details={"marker": "simulated"},
    )

    sends.assert_not_awaited()
    (event,) = await _reminder_events(db_session, front_desk_user)
    assert event.details["delivered"] is False
    assert event.details["marker"] == "simulated"


@pytest.mark.asyncio
async def test_deliver_new_message_sends_through_graph_and_audits_once(
    db_session, front_desk_user, monkeypatch
):
    monkeypatch.setattr(email_service.settings, "outlook_enabled", True)
    monkeypatch.setattr("app.services.outlook_auth.get_access_token", AsyncMock(return_value="t"))
    sends = AsyncMock(return_value=None)
    monkeypatch.setattr("app.services.outlook_client.send_mail", sends)

    await email_service.deliver_new_message(
        db_session,
        to_address="someone@example.com",
        subject="Subject",
        body="Body",
        actor=front_desk_user,
        case_id=None,
        action="test.new_message",
        details={},
    )

    sends.assert_awaited_once_with("t", "someone@example.com", "Subject", "Body")
    (event,) = await _reminder_events(db_session, front_desk_user)
    assert event.details["delivered"] is True


@pytest.mark.asyncio
async def test_a_failed_new_message_raises_and_audits_nothing(
    db_session, front_desk_user, monkeypatch
):
    """The same rule deliver_reply follows: a failure is never recorded as a
    delivered message."""
    monkeypatch.setattr(email_service.settings, "outlook_enabled", True)
    monkeypatch.setattr("app.services.outlook_auth.get_access_token", AsyncMock(return_value="t"))
    monkeypatch.setattr(
        "app.services.outlook_client.send_mail",
        AsyncMock(side_effect=httpx.HTTPError("graph is down")),
    )

    with pytest.raises(email_service.EmailSendError):
        await email_service.deliver_new_message(
            db_session,
            to_address="someone@example.com",
            subject="Subject",
            body="Body",
            actor=front_desk_user,
            case_id=None,
            action="test.new_message",
            details={},
        )

    assert await _reminder_events(db_session, front_desk_user) == []
