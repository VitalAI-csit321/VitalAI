"""Critic loop (build spec §6): deterministic rules, at most two regenerations."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.agents import graph as agent_graph
from app.agents.critic import critique
from app.agents.graph import build_graph, run_config, thread_id
from app.config import settings
from app.models.approval import ApprovalRequest
from app.models.audit import AuditEvent
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
