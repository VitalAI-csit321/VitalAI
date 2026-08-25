"""Inbox sync: dedupe, per-message failure containment, mark-as-read policy.

Runs the real ingest_email/draft_reply against the database, with only the
Graph transport and the LLM faked. Dedupe is the correctness-critical part:
without it a mark_as_read failure would cause the same patient email to be
reclassified and re-queued on every poll.
"""

import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.audit import AuditEvent
from app.schemas.email import EmailIngestRequest
from app.services import email_service, outlook_sync_service
from app.services.outlook_sync_service import _already_ingested, sync_inbox


class _FakeLLM:
    def __init__(self, response: str):
        self.response = response

    async def ainvoke(self, prompt: str) -> str:
        return self.response


def _graph_message(message_id: str = "AAMk-1", subject: str = "Appointment please") -> dict:
    return {
        "id": message_id,
        "subject": subject,
        "from": {"emailAddress": {"address": "patient@example.com"}},
        "toRecipients": [{"emailAddress": {"address": "clinic@example.com"}}],
        "body": {"content": f"<p>{subject}</p>"},
        "receivedDateTime": "2026-08-20T09:15:00Z",
    }


@pytest.fixture
def graph(monkeypatch):
    """Fake the whole Graph surface and the classifier LLM."""
    state = {"marked_read": [], "messages": [], "mark_fails": False}
    # Module-level attempt counters would otherwise leak between tests.
    outlook_sync_service._failed_attempts.clear()

    async def fake_token():
        return "tok"

    async def fake_get_unread(access_token, top=None):
        return state["messages"]

    async def fake_mark_as_read(access_token, message_id):
        if state["mark_fails"]:
            raise RuntimeError("Graph 403")
        state["marked_read"].append(message_id)

    monkeypatch.setattr("app.services.outlook_auth.get_access_token", fake_token)
    monkeypatch.setattr(outlook_sync_service.outlook_client, "get_unread_emails", fake_get_unread)
    monkeypatch.setattr(outlook_sync_service.outlook_client, "mark_as_read", fake_mark_as_read)
    monkeypatch.setattr(
        "app.services.email_service.get_llm",
        lambda: _FakeLLM(json.dumps({"category": "appointment_request", "confidence": 0.95})),
    )
    # appointment_request is non-clinical, so draft_reply() routes through
    # _generate_org_grounded_reply()'s real retrieve() call; no org content is
    # relevant here, so an empty result correctly falls back to the plain
    # reply path without needing a real Postgres/pgvector db.
    monkeypatch.setattr("app.rag.retrieval.retrieve", AsyncMock(return_value=[]))
    return state


@pytest.mark.asyncio
async def test_ingests_a_message_through_the_real_pipeline(db_session, front_desk_user, graph):
    graph["messages"] = [_graph_message()]

    summary = await sync_inbox(db_session, front_desk_user)

    assert summary.fetched == 1
    assert summary.ingested == 1
    assert summary.skipped_duplicate == 0
    assert graph["marked_read"] == ["AAMk-1"]


@pytest.mark.asyncio
async def test_same_message_is_not_ingested_twice(db_session, front_desk_user, graph):
    """The dedupe guarantee: a message still sitting unread in the mailbox
    (because mark_as_read failed) must not be reprocessed."""
    graph["messages"] = [_graph_message()]
    first = await sync_inbox(db_session, front_desk_user)
    assert first.ingested == 1

    second = await sync_inbox(db_session, front_desk_user)
    assert second.ingested == 0
    assert second.skipped_duplicate == 1


@pytest.mark.asyncio
async def test_mark_as_read_failure_does_not_undo_the_ingest(db_session, front_desk_user, graph):
    """Matthew's original try/except, preserved: the email is already committed
    and dedupe covers the next cycle, so a failed mark is tolerable."""
    graph["messages"] = [_graph_message()]
    graph["mark_fails"] = True

    summary = await sync_inbox(db_session, front_desk_user)

    assert summary.ingested == 1
    assert await _already_ingested(db_session, "AAMk-1") is True


@pytest.mark.asyncio
async def test_unparseable_message_is_skipped_not_fatal(db_session, front_desk_user, graph):
    """One bad message must not stop the rest of the batch."""
    bad = _graph_message("AAMk-bad")
    bad["body"] = {"content": "<style>.a{color:red}</style>"}
    graph["messages"] = [bad, _graph_message("AAMk-good")]

    summary = await sync_inbox(db_session, front_desk_user)

    assert summary.skipped_unparseable == 1
    assert summary.ingested == 1


@pytest.mark.asyncio
async def test_external_provenance_is_recorded_on_the_row(db_session, front_desk_user, graph):
    graph["messages"] = [_graph_message()]
    await sync_inbox(db_session, front_desk_user)

    assert await _already_ingested(db_session, "AAMk-1") is True
    # A directly-ingested email has no external id, so it must not collide
    # with the dedupe lookup.
    assert await _already_ingested(db_session, "never-seen") is False


@pytest.mark.asyncio
async def test_directly_ingested_email_does_not_block_dedupe(
    db_session, front_desk_user, monkeypatch
):
    """Emails created through POST /email/ingest carry no external id; several
    of them must be able to coexist (partial unique index on NOT NULL only)."""
    from app.services import email_service

    monkeypatch.setattr(
        "app.services.email_service.get_llm",
        lambda: _FakeLLM(json.dumps({"category": "appointment_request", "confidence": 0.95})),
    )
    for _ in range(2):
        await email_service.ingest_email(
            db_session,
            EmailIngestRequest(
                sender="a@example.com",
                recipient="clinic@example.com",
                subject="Hello",
                body="Hello there",
            ),
            front_desk_user,
        )
    assert await _already_ingested(db_session, "anything") is False


async def _audit_actions(db_session, action: str) -> list[str]:
    result = await db_session.execute(select(AuditEvent.action).where(AuditEvent.action == action))
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_unparseable_message_is_marked_read_so_it_stops_coming_back(
    db_session, front_desk_user, graph
):
    """Unparseable is permanent, not transient. Left unread it would be
    refetched and re-skipped on every poll for as long as the app runs."""
    bad = _graph_message("AAMk-bad")
    bad["body"] = {"content": "<style>.a{color:red}</style>"}
    graph["messages"] = [bad]

    summary = await sync_inbox(db_session, front_desk_user)

    assert summary.skipped_unparseable == 1
    assert graph["marked_read"] == ["AAMk-bad"]
    assert await _audit_actions(db_session, "email.ingest_unparseable") == [
        "email.ingest_unparseable"
    ]


@pytest.mark.asyncio
async def test_repeatedly_failing_message_is_abandoned_not_retried_forever(
    db_session, front_desk_user, graph, monkeypatch
):
    """The stuck-message loop: a message that always throws stays unread and
    comes back every cycle. It must be given up on, loudly, after a cap."""
    graph["messages"] = [_graph_message("AAMk-poison")]

    async def always_fails(*args, **kwargs):
        raise RuntimeError("classifier exploded")

    monkeypatch.setattr("app.services.email_service.ingest_email", always_fails)

    for _ in range(outlook_sync_service.MAX_INGEST_ATTEMPTS - 1):
        summary = await sync_inbox(db_session, front_desk_user)
        assert summary.failed == 1
        # Still under the cap: left unread on purpose, so a transient fault
        # gets another chance next cycle.
        assert graph["marked_read"] == []

    final = await sync_inbox(db_session, front_desk_user)

    assert final.failed == 1
    assert graph["marked_read"] == ["AAMk-poison"]
    assert await _audit_actions(db_session, "email.ingest_abandoned") == ["email.ingest_abandoned"]


@pytest.mark.asyncio
async def test_a_successful_ingest_clears_earlier_failures(
    db_session, front_desk_user, graph, monkeypatch
):
    """Attempts must count consecutive failures, not lifetime ones: a message
    that recovers should not be abandoned by old, unrelated failures."""
    graph["messages"] = [_graph_message("AAMk-flaky")]
    real_ingest = email_service.ingest_email

    async def fails_once(*args, **kwargs):
        monkeypatch.setattr("app.services.email_service.ingest_email", real_ingest)
        raise RuntimeError("transient blip")

    monkeypatch.setattr("app.services.email_service.ingest_email", fails_once)

    assert (await sync_inbox(db_session, front_desk_user)).failed == 1
    assert outlook_sync_service._failed_attempts.get("AAMk-flaky") == 1

    assert (await sync_inbox(db_session, front_desk_user)).ingested == 1
    assert "AAMk-flaky" not in outlook_sync_service._failed_attempts


@pytest.mark.asyncio
async def test_one_failure_does_not_poison_the_rest_of_the_batch(
    db_session, front_desk_user, graph, monkeypatch
):
    """Containment across a rollback: rolling back expires the actor instance,
    and every later message in the batch reads it again."""
    graph["messages"] = [_graph_message("AAMk-bad"), _graph_message("AAMk-good")]
    real_ingest = email_service.ingest_email

    async def fails_for_the_first_only(db, payload, actor):
        if str(payload.external_id) == "AAMk-bad":
            raise RuntimeError("transient blip")
        return await real_ingest(db, payload, actor)

    monkeypatch.setattr("app.services.email_service.ingest_email", fails_for_the_first_only)

    summary = await sync_inbox(db_session, front_desk_user)

    assert summary.failed == 1
    assert summary.ingested == 1
    assert graph["marked_read"] == ["AAMk-good"]
