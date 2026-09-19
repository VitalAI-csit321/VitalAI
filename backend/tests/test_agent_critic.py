"""Critic loop (build spec §6): deterministic rules, at most two regenerations."""

from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy import select

from app.agents import graph as agent_graph
from app.agents.graph import build_graph, run_config, thread_id
from app.config import settings
from app.models.approval import ApprovalRequest
from app.models.audit import AuditEvent
from app.models.task import Task
from app.services.draft_critic import critique
from app.services.task_routing_gate import TaskRoutingGateResult, TaskRoutingOutcome
from tests.agent_fakes import DRAFT, FakeLLM, seed_email

BAD = "Thanks for asking. This medication looks appropriate to continue."
FLAGGED = TaskRoutingGateResult(
    outcome=TaskRoutingOutcome.AUTO_ROUTED_FLAGGED, override_reason=None
)


def test_a_draft_judging_clinical_suitability_is_rejected_with_a_reason():
    reason = critique(BAD)
    assert reason is not None
    assert "suitab" in reason


@pytest.mark.parametrize("draft", ["", "   \n", None])
def test_an_empty_draft_is_rejected(draft):
    assert critique(draft) is not None


def test_an_ordinary_reply_passes():
    assert critique("We open at 9am on Saturdays.") is None


@pytest.fixture
def retrieve(monkeypatch):
    mock = AsyncMock(return_value=[])
    monkeypatch.setattr("app.rag.retrieval.retrieve", mock)
    return mock


@pytest.fixture
def outlook(monkeypatch):
    monkeypatch.setattr(settings, "outlook_enabled", True)
    monkeypatch.setattr("app.services.outlook_auth.get_access_token", AsyncMock(return_value="t"))
    sends = AsyncMock(return_value=None)
    monkeypatch.setattr("app.services.outlook_client.send_reply", sends)
    return sends


async def _run(db_session, agent_saver, monkeypatch, replies):
    llm = FakeLLM(replies=replies)
    monkeypatch.setattr("app.services.email_service.get_llm", lambda: llm)
    email, task = await seed_email(db_session, external_id="AAMk-critic")
    await agent_graph.start(task.id, email.id, None, FLAGGED, 0.8)
    snapshot = (
        await build_graph()
        .compile(checkpointer=agent_saver)
        .aget_state(run_config(thread_id("email", str(email.id))))
    )
    return llm, email, task, snapshot


async def _approvals(db_session, task):
    rows = (await db_session.execute(select(ApprovalRequest))).scalars().all()
    return [r for r in rows if r.payload.get("task_id") == str(task.id)]


async def test_rejected_draft_is_regenerated_with_the_reason_in_the_prompt(
    db_session, agent_saver, monkeypatch, retrieve
):
    llm, email, task, snapshot = await _run(db_session, agent_saver, monkeypatch, [BAD, DRAFT])

    first, second = llm.draft_prompts
    reason = critique(BAD)
    assert reason not in first
    assert reason in second
    # Feedback shapes the prompt, never what is retrieved.
    assert [c.args[1] for c in retrieve.call_args_list] == [email.body, email.body]
    assert snapshot.values["revision_count"] == 1
    assert snapshot.values["critic_verdict"] == "pass"
    assert snapshot.next == ("await_approval",)
    (approval,) = await _approvals(db_session, task)
    assert approval.payload["draft"] == DRAFT


async def test_three_failing_drafts_escalate_with_no_approval_and_no_send(
    db_session, agent_saver, monkeypatch, retrieve, outlook
):
    llm, email, task, snapshot = await _run(db_session, agent_saver, monkeypatch, [BAD])

    # The first draft plus two regenerations, then stop.
    assert len(llm.draft_prompts) == 3
    assert snapshot.values["revision_count"] == 2
    assert snapshot.values["dispatch_result"] == "escalated"
    assert snapshot.next == ()
    assert await _approvals(db_session, task) == []
    outlook.assert_not_awaited()
    await db_session.refresh(task)
    assert task.draft_sent is False
    assert task.draft_text is None
    assert critique(BAD) in task.handover_context
    events = (
        (await db_session.execute(select(AuditEvent).where(AuditEvent.case_id == email.case_id)))
        .scalars()
        .all()
    )
    assert "agent.critic_escalated" in [e.action for e in events]


# --- flag-off path: critic only, no regeneration ---------------------------------


async def _flag_off_bad_draft(client, headers, monkeypatch, outlook):
    """An email that passes every auto-send condition, except its draft judges
    medication suitability."""
    monkeypatch.setattr(settings, "agentic_pipeline_enabled", False)
    llm = FakeLLM()
    monkeypatch.setattr("app.services.email_service.get_llm", lambda: llm)
    monkeypatch.setattr(
        "app.services.email_service._generate_org_grounded_reply",
        AsyncMock(return_value=(BAD, True)),
    )
    response = await client.post(
        "/api/v1/email/ingest",
        json={
            "sender": "patient@example.com",
            "recipient": "clinic@example.com",
            "subject": "Question",
            "body": "Can I keep taking my tablets?",
            "external_id": "AAMk-flagoff",
            "external_source": "outlook",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["task_id"]


async def test_flag_off_rejected_draft_is_held_for_staff_with_the_reason(
    client, front_desk_headers, db_session, monkeypatch, outlook
):
    task_id = await _flag_off_bad_draft(client, front_desk_headers, monkeypatch, outlook)

    outlook.assert_not_awaited()
    task = await db_session.get(Task, UUID(task_id))
    await db_session.refresh(task)
    assert task.draft_sent is False
    # Kept, so staff can edit it rather than start from nothing.
    assert task.draft_text == BAD
    assert critique(BAD) in task.handover_context
    (approval,) = await _approvals(db_session, task)
    assert approval.payload["critic_reason"] == critique(BAD)
    assert task.draft_approval_id == approval.id


async def test_flag_off_staff_edit_and_approve_sends_their_text(
    client, front_desk_headers, admin_headers, db_session, monkeypatch, outlook
):
    task_id = await _flag_off_bad_draft(client, front_desk_headers, monkeypatch, outlook)
    task = await db_session.get(Task, UUID(task_id))
    (approval,) = await _approvals(db_session, task)
    edited = "Thanks for asking. I have passed your question to the clinical team."

    response = await client.post(
        f"/api/v1/approvals/{approval.id}/approve",
        json={"resolved_payload": {**approval.payload, "draft": edited}},
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    outlook.assert_awaited_once_with("t", "AAMk-flagoff", edited)
    await db_session.refresh(task)
    assert task.draft_sent is True
    assert task.draft_text == edited


# --- §5.1: a critic-corrected draft always reaches a human ------------------------

AUTO = TaskRoutingGateResult(outcome=TaskRoutingOutcome.AUTO_ROUTED, override_reason=None)


async def test_a_draft_the_critic_corrected_goes_to_approval_not_auto_send(
    db_session, agent_saver, monkeypatch, outlook
):
    """Rejected once, then passes the critic and meets every auto-send condition
    (fully confident, grounded, worthy, non-clinical). Before reply_risk_tier the
    rewrite went straight to the patient."""
    llm = FakeLLM()
    monkeypatch.setattr("app.services.email_service.get_llm", lambda: llm)
    monkeypatch.setattr(
        "app.services.email_service._generate_org_grounded_reply",
        AsyncMock(side_effect=[(BAD, True), (DRAFT, True)]),
    )
    email, task = await seed_email(db_session, external_id="AAMk-corrected")

    await agent_graph.start(task.id, email.id, None, AUTO, 0.95)

    snapshot = (
        await build_graph()
        .compile(checkpointer=agent_saver)
        .aget_state(run_config(thread_id("email", str(email.id))))
    )
    assert snapshot.values["revision_count"] == 1
    assert snapshot.values["critic_verdict"] == "pass"
    assert snapshot.values["risk_tier"] == "high"
    assert snapshot.next == ("await_approval",)
    outlook.assert_not_awaited()
    (approval,) = await _approvals(db_session, task)
    assert approval.payload["draft"] == DRAFT
    await db_session.refresh(task)
    assert task.draft_sent is False
