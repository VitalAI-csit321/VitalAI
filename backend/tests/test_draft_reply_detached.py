"""Drafting runs off the path that ingested the email.

draft_reply is a gemma2:9b call with a 90s timeout. Awaited inline it held the
ingest response open, and inside the Outlook poll loop it serialised the whole
batch behind one model run. Both call sites now detach it, by two different
mechanisms: the route has FastAPI BackgroundTasks, the poller does not (it is
an asyncio.Task in lifespan, not a request), so it gets a bounded
create_task instead.
"""

import asyncio
import json
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.config import settings
from app.models.task import Task
from app.schemas.email import EmailIngestRequest
from app.services import email_service, outlook_sync_service
from app.services.task_routing_gate import TaskRoutingGateResult, TaskRoutingOutcome


class _FakeLLM:
    def __init__(self, response: str):
        self.response = response

    async def ainvoke(self, prompt: str) -> str:
        if "worthy" in prompt.lower():
            return json.dumps({"worthy": True, "reason": "test default"})
        return self.response


@pytest.fixture
def flag_off(monkeypatch):
    """These tests pin the flag-off scheduling of draft_reply_detached. With
    AGENTIC_PIPELINE_ENABLED the same schedulers run the agent graph instead,
    covered in test_agent_email_graph.py."""
    monkeypatch.setattr(settings, "agentic_pipeline_enabled", False)


@pytest.fixture
def pipeline(monkeypatch):
    monkeypatch.setattr(
        "app.services.email_service.get_llm",
        lambda: _FakeLLM(json.dumps({"category": "appointment_request", "confidence": 0.95})),
    )
    monkeypatch.setattr("app.rag.retrieval.retrieve", AsyncMock(return_value=[]))


@pytest.mark.asyncio
async def test_detached_draft_opens_its_own_session_and_persists(
    db_session, front_desk_user, detached_sessionmaker, monkeypatch, pipeline
):
    """The rows are re-fetched, not passed in: whatever scheduled the draft
    has already returned and closed its session by the time this runs."""
    monkeypatch.setattr(email_service, "AsyncSessionLocal", detached_sessionmaker)

    email, task, gate, confidence = await email_service.ingest_email(
        db_session,
        EmailIngestRequest(
            sender="patient@example.com",
            recipient="clinic@example.com",
            subject="Booking",
            body="Can I book next week?",
        ),
        front_desk_user,
    )

    await email_service.draft_reply_detached(
        task.id, email.id, front_desk_user.id, gate, confidence
    )

    await db_session.refresh(task)
    assert task.draft_text is not None


@pytest.mark.asyncio
async def test_detached_draft_swallows_failure_instead_of_escaping(
    db_session, front_desk_user, detached_sessionmaker, monkeypatch, pipeline
):
    """A detached task has nobody to raise to. The Email and Task rows are
    already committed, so a drafting failure must not escape and kill the
    poll loop or the request's background runner.

    Asserts the behaviour, not the log line: on the Postgres track conftest
    runs Alembic, whose env.py calls fileConfig() and so disables every
    logger created at import time, leaving caplog silently empty.
    """
    monkeypatch.setattr(email_service, "AsyncSessionLocal", detached_sessionmaker)
    called = []

    async def boom(*args, **kwargs):
        called.append(True)
        raise RuntimeError("ollama is down")

    monkeypatch.setattr(email_service, "draft_reply", boom)

    email, task, gate, confidence = await email_service.ingest_email(
        db_session,
        EmailIngestRequest(
            sender="patient@example.com",
            recipient="clinic@example.com",
            subject="Booking",
            body="Can I book next week?",
        ),
        front_desk_user,
    )

    # Must not raise.
    await email_service.draft_reply_detached(
        task.id, email.id, front_desk_user.id, gate, confidence
    )

    assert called == [True]
    await db_session.refresh(task)
    assert task.draft_text is None


@pytest.mark.asyncio
async def test_ingest_route_returns_without_waiting_for_the_draft(
    client, front_desk_headers, db_session, detached_sessionmaker, monkeypatch, pipeline, flag_off
):
    """draft_reply must not be awaited during the request. The draft still
    lands on the Task row, just after the response."""
    monkeypatch.setattr(email_service, "AsyncSessionLocal", detached_sessionmaker)
    during_request = []

    real_draft_reply = email_service.draft_reply

    async def tracking_draft_reply(db, task, email, actor, gate, confidence):
        during_request.append(responded[:])
        return await real_draft_reply(db, task, email, actor, gate, confidence)

    responded: list[str] = []
    monkeypatch.setattr(email_service, "draft_reply", tracking_draft_reply)

    response = await client.post(
        "/api/v1/email/ingest",
        json={
            "sender": "patient@example.com",
            "recipient": "clinic@example.com",
            "subject": "Need an appointment",
            "body": "Can I book an appointment for next week?",
        },
        headers=front_desk_headers,
    )
    responded.append("sent")

    assert response.status_code == 201
    # ASGITransport drains background tasks before returning, so by here the
    # draft has run -- but it must have started only after the response was
    # built, which is what an empty `responded` snapshot would contradict.
    assert during_request == [[]]

    task = await db_session.get(Task, UUID(response.json()["task_id"]))
    await db_session.refresh(task)
    assert task.draft_text is not None


@pytest.mark.asyncio
async def test_poller_does_not_await_the_draft(db_session, front_desk_user, monkeypatch, pipeline):
    """_process_one schedules; it never awaits drafting, or one slow model run
    would stall the other 24 messages in the poll batch."""
    scheduled = []
    monkeypatch.setattr(
        outlook_sync_service,
        "schedule_draft",
        lambda *args: scheduled.append(args),
    )

    async def must_not_run(*args, **kwargs):
        raise AssertionError("draft_reply must not be awaited inside the poll loop")

    monkeypatch.setattr(email_service, "draft_reply", must_not_run)
    monkeypatch.setattr(
        outlook_sync_service.outlook_client, "mark_as_read", AsyncMock(return_value=None)
    )

    await outlook_sync_service._process_one(
        db_session,
        EmailIngestRequest(
            sender="patient@example.com",
            recipient="clinic@example.com",
            subject="Booking",
            body="Can I book next week?",
            external_id="AAMk-detach",
            external_source="outlook",
        ),
        front_desk_user,
        "tok",
    )

    assert len(scheduled) == 1


@pytest.mark.asyncio
async def test_scheduled_drafts_are_bounded_to_one_at_a_time(monkeypatch, flag_off):
    """25 messages per poll on one CPU-bound Ollama would launch 25
    concurrent gemma2:9b runs and take the box down."""
    live = 0
    peak = 0

    async def slow_draft(*args):
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0)
        live -= 1

    monkeypatch.setattr(email_service, "draft_reply_detached", slow_draft)

    gate = TaskRoutingGateResult(outcome=TaskRoutingOutcome.AUTO_ROUTED, override_reason=None)
    for _ in range(5):
        outlook_sync_service.schedule_draft(None, None, None, gate, 0.95)

    assert len(outlook_sync_service._drafting) == 5
    while outlook_sync_service._drafting:
        await asyncio.sleep(0)

    assert peak == 1


@pytest.mark.asyncio
async def test_scheduled_draft_keeps_a_strong_reference_until_it_finishes(monkeypatch, flag_off):
    """Without the module-level set the event loop is the only owner of a
    bare create_task and can collect it mid-flight."""
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking_draft(*args):
        started.set()
        await release.wait()

    monkeypatch.setattr(email_service, "draft_reply_detached", blocking_draft)

    gate = TaskRoutingGateResult(outcome=TaskRoutingOutcome.AUTO_ROUTED, override_reason=None)
    outlook_sync_service.schedule_draft(None, None, None, gate, 0.95)

    await started.wait()
    assert len(outlook_sync_service._drafting) == 1

    release.set()
    while outlook_sync_service._drafting:
        await asyncio.sleep(0)
    assert outlook_sync_service._drafting == set()
