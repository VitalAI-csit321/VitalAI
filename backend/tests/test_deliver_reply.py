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


def test_outlook_send_reply_has_exactly_one_caller_in_app():
    """Every outbound reply goes through deliver_reply. A second caller would
    be a send path without P1's draft_sent guard."""
    app_dir = Path(__file__).resolve().parent.parent / "app"
    callers = [
        str(p.relative_to(app_dir))
        for p in app_dir.rglob("*.py")
        for _ in re.finditer(r"outlook_client\.send_reply\(", p.read_text())
    ]
    assert callers == ["services/email_service.py"]
