"""Safety behaviour of the outbound path.

Three properties matter here and none of them are about Outlook mechanics:

1. With the connector live, no reply is auto-sent on confidence alone. Before
   this feature "sent" was a database flag; now it means a message actually
   reaches a patient, so the high-confidence shortcut must close.
2. A failed delivery is never recorded as sent.
3. Turning the connector off does not bypass the reply-worthiness gate's
   safety conditions either: an ungrounded draft still requires approval
   regardless of outlook_enabled, see app.services.reply_gate.
"""

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from app.models.approval import ApprovalRequest, ApprovalStatus
from app.routes.approvals import EmailSendError, _execute_email_draft_reply
from app.schemas.email import EmailIngestRequest
from app.services import email_service


class _FakeLLM:
    """Answers the classifier's canned response, and answers WORTHY to the
    reply-worthiness gate's separate call -- these tests aren't exercising
    that gate (see test_reply_gate.py), they just need it out of the way.
    """

    def __init__(self, response: str):
        self.response = response

    async def ainvoke(self, prompt: str) -> str:
        if "worthy" in prompt.lower():
            return json.dumps({"worthy": True, "reason": "test default"})
        return self.response


async def _ingest_high_confidence(db_session, actor, monkeypatch, **request_kwargs):
    monkeypatch.setattr(
        "app.services.email_service.get_llm",
        lambda: _FakeLLM(json.dumps({"category": "appointment_request", "confidence": 0.99})),
    )
    # appointment_request is non-clinical, so draft_reply() routes through
    # _generate_org_grounded_reply()'s real retrieve() call. No org content is
    # relevant to these send-gating tests, so an empty result correctly falls
    # back to the plain reply path without needing a real Postgres/pgvector db.
    monkeypatch.setattr("app.rag.retrieval.retrieve", AsyncMock(return_value=[]))
    payload = EmailIngestRequest(
        sender="patient@example.com",
        recipient="clinic@example.com",
        subject="Booking",
        body="Please book me in for next Tuesday.",
        **request_kwargs,
    )
    return await email_service.ingest_email(db_session, payload, actor)


@pytest.mark.asyncio
async def test_ungrounded_reply_requires_approval_even_with_connector_off(
    db_session, front_desk_user, monkeypatch
):
    """The reply-worthiness gate's grounding requirement isn't an
    Outlook-only safeguard: _ingest_high_confidence's empty retrieval means
    the draft falls back to a generic, ungrounded reply, which must go to
    approval whether or not the connector is live."""
    monkeypatch.setattr(email_service.settings, "outlook_enabled", False)
    email, task, gate, confidence = await _ingest_high_confidence(
        db_session, front_desk_user, monkeypatch
    )

    outcome = await email_service.draft_reply(
        db_session, task, email, front_desk_user, gate, confidence
    )

    assert outcome.sent is False
    assert outcome.approval_id is not None


@pytest.mark.asyncio
async def test_connector_on_forces_every_reply_through_approval(
    db_session, front_desk_user, monkeypatch
):
    """The safety property: 0.99 confidence is no longer sufficient to send."""
    monkeypatch.setattr(email_service.settings, "outlook_enabled", True)
    email, task, gate, confidence = await _ingest_high_confidence(
        db_session, front_desk_user, monkeypatch
    )

    outcome = await email_service.draft_reply(
        db_session, task, email, front_desk_user, gate, confidence
    )

    assert outcome.sent is False
    assert outcome.approval_id is not None


@pytest.mark.asyncio
async def test_approved_draft_sends_through_graph(db_session, front_desk_user, monkeypatch):
    monkeypatch.setattr("app.routes.approvals.settings.outlook_enabled", True)
    sent: dict = {}

    async def fake_token():
        return "tok"

    async def fake_send(access_token, message_id, body):
        sent["message_id"] = message_id
        sent["body"] = body

    monkeypatch.setattr("app.routes.approvals.outlook_auth.get_access_token", fake_token)
    monkeypatch.setattr("app.routes.approvals.outlook_client.send_reply", fake_send)

    email, task, _, _ = await _ingest_high_confidence(
        db_session,
        front_desk_user,
        monkeypatch,
        external_id="AAMk-send",
        external_source="outlook",
    )
    approval = ApprovalRequest(
        action_type="email.draft_reply",
        status=ApprovalStatus.APPROVED,
        payload={"email_id": str(email.id), "task_id": str(task.id), "draft": "You are booked."},
        case_id=email.case_id,
        requested_by_id=front_desk_user.id,
    )
    db_session.add(approval)
    await db_session.flush()

    await _execute_email_draft_reply(db_session, approval, front_desk_user)

    assert sent["message_id"] == "AAMk-send"
    assert sent["body"] == "You are booked."
    await db_session.refresh(task)
    assert task.draft_sent is True


@pytest.mark.asyncio
async def test_failed_send_is_not_recorded_as_sent(db_session, front_desk_user, monkeypatch):
    """A Graph rejection must surface, not silently mark the reply delivered."""
    monkeypatch.setattr("app.routes.approvals.settings.outlook_enabled", True)

    async def fake_token():
        return "tok"

    async def failing_send(access_token, message_id, body):
        raise httpx.HTTPStatusError(
            "403", request=httpx.Request("POST", "https://graph"), response=httpx.Response(403)
        )

    monkeypatch.setattr("app.routes.approvals.outlook_auth.get_access_token", fake_token)
    monkeypatch.setattr("app.routes.approvals.outlook_client.send_reply", failing_send)

    email, task, _, _ = await _ingest_high_confidence(
        db_session,
        front_desk_user,
        monkeypatch,
        external_id="AAMk-fail",
        external_source="outlook",
    )
    approval = ApprovalRequest(
        action_type="email.draft_reply",
        status=ApprovalStatus.APPROVED,
        payload={"email_id": str(email.id), "task_id": str(task.id), "draft": "Reply text."},
        case_id=email.case_id,
        requested_by_id=front_desk_user.id,
    )
    db_session.add(approval)
    await db_session.flush()

    with pytest.raises(EmailSendError):
        await _execute_email_draft_reply(db_session, approval, front_desk_user)

    await db_session.refresh(task)
    assert task.draft_sent is False


@pytest.mark.asyncio
async def test_simulated_send_untouched_when_connector_off(
    db_session, front_desk_user, monkeypatch
):
    """With the connector off the executor must not reach for a token at all."""
    monkeypatch.setattr("app.routes.approvals.settings.outlook_enabled", False)

    async def explode():
        raise AssertionError("must not authenticate when the connector is off")

    monkeypatch.setattr("app.routes.approvals.outlook_auth.get_access_token", explode)

    email, task, _, _ = await _ingest_high_confidence(
        db_session, front_desk_user, monkeypatch, external_id="AAMk-x", external_source="outlook"
    )
    approval = ApprovalRequest(
        action_type="email.draft_reply",
        status=ApprovalStatus.APPROVED,
        payload={"email_id": str(email.id), "task_id": str(task.id), "draft": "Reply."},
        case_id=email.case_id,
        requested_by_id=front_desk_user.id,
    )
    db_session.add(approval)
    await db_session.flush()

    await _execute_email_draft_reply(db_session, approval, front_desk_user)

    await db_session.refresh(task)
    assert task.draft_sent is True
