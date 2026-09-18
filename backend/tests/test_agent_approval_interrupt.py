"""Approval interrupt (build spec §3): the create_approval / await_approval split.

interrupt() re-runs its node from the top on resume. If the approval row were
written in the same node as interrupt(), every resume would mint a second
ApprovalRequest. These tests pin that down.
"""

import os
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import create_async_engine

from app.agents.graph import build_graph, make_context, run_config, thread_id
from app.config import settings
from app.models.approval import ApprovalRequest, ApprovalStatus
from app.services import approval_service
from tests.test_agent_graph_core import _worker


def _email(source_id: str, case_id: str | None = None) -> dict:
    return {
        "channel": "email",
        "source_id": source_id,
        "case_id": case_id,
        "task_id": None,
        "draft_text": "Thanks, we have your request.",
        "risk_tier": "high",
    }


async def _rows(db, tid: str) -> list[ApprovalRequest]:
    result = await db.execute(select(ApprovalRequest).where(ApprovalRequest.external_ref == tid))
    return list(result.scalars().all())


async def _paused(detached_sessionmaker, source_id: str | None = None, case_id: str | None = None):
    graph = build_graph().compile(checkpointer=InMemorySaver())
    ctx = await make_context(detached_sessionmaker)
    source_id = source_id or str(uuid4())
    tid = thread_id("email", source_id)
    result = await graph.ainvoke(_email(source_id, case_id), run_config(tid), context=ctx)
    return graph, ctx, tid, result


async def test_interrupt_returns_and_leaves_one_pending_row_keyed_by_thread(
    detached_sessionmaker, db_session
):
    _, _, tid, result = await _paused(detached_sessionmaker)

    # An interrupted ainvoke returns, it does not raise.
    assert "__interrupt__" in result
    rows = await _rows(db_session, tid)
    assert len(rows) == 1
    assert rows[0].status == ApprovalStatus.PENDING
    assert rows[0].external_ref == tid
    assert rows[0].payload["draft"] == "Thanks, we have your request."
    assert result["approval_request_id"] == str(rows[0].id)


async def test_exactly_one_approval_row_after_resume(detached_sessionmaker, db_session, admin_user):
    graph, ctx, tid, _ = await _paused(detached_sessionmaker)
    # Decided off the queue row, as a human would, not off graph state.
    (row,) = await _rows(db_session, tid)
    await approval_service.approve(db_session, row.id, admin_user)

    final = await graph.ainvoke(Command(resume={"approved": True}), run_config(tid), context=ctx)

    assert len(await _rows(db_session, tid)) == 1
    assert final["approval_status"] == "approved"
    snapshot = await graph.aget_state(run_config(tid))
    assert snapshot.next == ()
    assert not snapshot.interrupts


async def test_reject_resumes_and_reaches_end(detached_sessionmaker, db_session, admin_user):
    graph, ctx, tid, _ = await _paused(detached_sessionmaker)
    # Decided off the queue row, as a human would, not off graph state.
    (row,) = await _rows(db_session, tid)
    await approval_service.reject(db_session, row.id, admin_user)

    final = await graph.ainvoke(Command(resume={"approved": False}), run_config(tid), context=ctx)

    assert final["approval_status"] == "rejected"
    snapshot = await graph.aget_state(run_config(tid))
    assert snapshot.next == ()
    assert not snapshot.interrupts
    rows = await _rows(db_session, tid)
    assert [r.status for r in rows] == [ApprovalStatus.REJECTED]


async def test_edited_draft_from_the_human_lands_in_state(detached_sessionmaker):
    graph, ctx, tid, _ = await _paused(detached_sessionmaker)

    final = await graph.ainvoke(
        Command(resume={"approved": True, "draft": "Edited by staff."}),
        run_config(tid),
        context=ctx,
    )

    assert final["draft_text"] == "Edited by staff."


async def test_two_emails_on_one_case_get_separate_threads_and_rows(
    detached_sessionmaker, db_session, seeded_case
):
    case_id = str(seeded_case.id)
    _, _, first, _ = await _paused(detached_sessionmaker, case_id=case_id)
    _, _, second, _ = await _paused(detached_sessionmaker, case_id=case_id)

    assert first != second
    assert len(await _rows(db_session, first)) == 1
    assert len(await _rows(db_session, second)) == 1


# --- the approvals route schedules the resume --------------------------------


@pytest.fixture
def resumes(monkeypatch):
    calls = []

    async def record(tid, decision):
        calls.append((tid, decision))

    monkeypatch.setattr("app.agents.graph.resume", record)
    return calls


async def _agent_row(db_session, external_ref: str | None) -> ApprovalRequest:
    return await approval_service.create_approval_request(
        db_session,
        action_type="email.draft_reply",
        payload={"draft": "Original.", "email_id": None, "task_id": None},
        external_ref=external_ref,
    )


async def test_approve_schedules_resume_with_the_approved_text(
    client, admin_headers, db_session, resumes, monkeypatch
):
    monkeypatch.setattr(settings, "agentic_pipeline_enabled", True)
    row = await _agent_row(db_session, "email:abc")

    response = await client.post(
        f"/api/v1/approvals/{row.id}/approve",
        json={"resolved_payload": {"draft": "Edited.", "email_id": None, "task_id": None}},
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    assert resumes == [("email:abc", {"approved": True, "draft": "Edited."})]


async def test_reject_schedules_resume_so_the_thread_is_not_stranded(
    client, admin_headers, db_session, resumes, monkeypatch
):
    monkeypatch.setattr(settings, "agentic_pipeline_enabled", True)
    row = await _agent_row(db_session, "email:abc")

    response = await client.post(
        f"/api/v1/approvals/{row.id}/reject", json={}, headers=admin_headers
    )

    assert response.status_code == 200, response.text
    assert resumes == [("email:abc", {"approved": False})]


async def test_flag_off_schedules_no_resume(
    client, admin_headers, db_session, resumes, monkeypatch
):
    monkeypatch.setattr(settings, "agentic_pipeline_enabled", False)
    row = await _agent_row(db_session, "email:abc")
    other = await _agent_row(db_session, "email:def")

    await client.post(f"/api/v1/approvals/{row.id}/approve", json={}, headers=admin_headers)
    await client.post(f"/api/v1/approvals/{other.id}/reject", json={}, headers=admin_headers)

    assert resumes == []


async def test_non_agent_row_schedules_no_resume(
    client, admin_headers, db_session, resumes, monkeypatch
):
    monkeypatch.setattr(settings, "agentic_pipeline_enabled", True)
    row = await _agent_row(db_session, None)

    await client.post(f"/api/v1/approvals/{row.id}/approve", json={}, headers=admin_headers)

    assert resumes == []


# --- cross-process, real Postgres --------------------------------------------

_XPROC = (
    os.environ["DATABASE_URL"].startswith("postgresql") and os.environ.get("AGENT_XPROC") == "1"
)


@pytest.mark.skipif(
    not _XPROC,
    reason="needs Postgres and AGENT_XPROC=1: commits audit rows, which the "
    "audit trigger makes undeletable, so it must only run on a throwaway database",
)
@pytest.mark.parametrize("decision", ["approve", "reject"])
async def test_pause_in_one_process_decide_and_resume_in_another(decision):
    from app.agents.checkpointer import open_checkpointer

    tid = thread_id("email", str(uuid4()))
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        await _worker("approval-start", tid)

        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(ApprovalRequest).where(ApprovalRequest.external_ref == tid)
                )
            ).all()
        assert len(rows) == 1
        approval_id = str(rows[0].id)
        assert rows[0].status == ApprovalStatus.PENDING

        await _worker("approval-decide", tid, approval_id, decision)

        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(ApprovalRequest).where(ApprovalRequest.external_ref == tid)
                )
            ).all()
        assert len(rows) == 1  # the resume did not mint a second row
        expected = "approved" if decision == "approve" else "rejected"
        assert rows[0].status == ApprovalStatus(expected)

        async with open_checkpointer() as saver:
            snapshot = await build_graph().compile(checkpointer=saver).aget_state(run_config(tid))
        assert snapshot.values["approval_status"] == expected
        assert snapshot.next == ()
        assert not snapshot.interrupts
    finally:
        async with engine.begin() as conn:
            await conn.execute(delete(ApprovalRequest).where(ApprovalRequest.external_ref == tid))
        await engine.dispose()
        async with open_checkpointer() as saver:
            await saver.adelete_thread(tid)
