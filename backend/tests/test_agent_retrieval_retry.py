"""Retrieval retry (build spec §7): one reformulation, graph only, floor 0.44.

A draft grounded only on the second attempt is HIGH risk and must never
auto-send. Flag off, nothing here runs: no reformulation, no extra LLM call.
"""

from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.agents import graph as agent_graph
from app.agents.graph import build_graph, run_config, thread_id
from app.config import settings
from app.llm import guardrail
from app.models.approval import ApprovalRequest
from app.models.task import Task
from app.rag import retry
from app.rag.retrieval import RetrievalContext, RetrievedChunk
from app.rag.retry import Reformulator, retrieve_gated
from app.services.task_routing_gate import TaskRoutingGateResult, TaskRoutingOutcome
from tests.agent_fakes import DRAFT, FakeLLM, seed_email

AUTO = TaskRoutingGateResult(outcome=TaskRoutingOutcome.AUTO_ROUTED, override_reason=None)
BODY = "What time do you open on Saturdays?"
REWRITE = "saturday opening hours"
CTX = RetrievalContext(patient_id=None, allowed_scopes=["general"], role="operator")


def _chunk(score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid4(),
        patient_id=None,
        access_scope="general",
        source_document_id=uuid4(),
        doc_type="org_profile",
        chunk_index=0,
        attachment_uri=None,
        content="We open 9am to 1pm on Saturdays.",
        score=score,
        distance=1 - score,
    )


BELOW, ABOVE = (
    [_chunk(settings.sufficiency_floor - 0.1)],
    [_chunk(settings.sufficiency_floor + 0.1)],
)


@pytest.fixture
def guarded_routes(monkeypatch):
    """Every guarded_invoke route, while still calling the real one."""
    routes: list[str] = []
    real = guardrail.guarded_invoke

    async def spy(db, llm, prompt, *, actor, route):
        routes.append(route)
        return await real(db, llm, prompt, actor=actor, route=route)

    monkeypatch.setattr(retry, "guarded_invoke", spy)
    return routes


@pytest.fixture
def outlook(monkeypatch):
    monkeypatch.setattr(settings, "outlook_enabled", True)
    monkeypatch.setattr("app.services.outlook_auth.get_access_token", AsyncMock(return_value="t"))
    sends = AsyncMock(return_value=None)
    monkeypatch.setattr("app.services.outlook_client.send_reply", sends)
    return sends


# --- the helper -------------------------------------------------------------------


async def test_without_a_reformulator_there_is_one_attempt(db_session, monkeypatch):
    retrieve = AsyncMock(return_value=BELOW)
    monkeypatch.setattr("app.rag.retrieval.retrieve", retrieve)

    outcome = await retrieve_gated(db_session, BODY, CTX)

    assert outcome.sufficient is False
    assert retrieve.await_count == 1


async def test_second_attempt_uses_a_different_query_through_guarded_invoke(
    db_session, admin_user, monkeypatch, guarded_routes
):
    retrieve = AsyncMock(side_effect=[BELOW, ABOVE])
    monkeypatch.setattr("app.rag.retrieval.retrieve", retrieve)
    reformulator = Reformulator(db_session, admin_user, FakeLLM(reformulation=REWRITE))

    outcome = await retrieve_gated(db_session, BODY, CTX, reformulate=reformulator)

    assert outcome.sufficient is True
    assert [c.args[1] for c in retrieve.await_args_list] == [BODY, REWRITE]
    assert guarded_routes == ["email.reformulate"]
    assert (reformulator.attempts, reformulator.query, reformulator.sufficient) == (
        2,
        REWRITE,
        True,
    )


@pytest.mark.parametrize("rewrite", ["", "   ", "  what time do you OPEN on saturdays? "])
async def test_an_empty_or_unchanged_rewrite_skips_the_retry_and_counts_as_failed(
    db_session, admin_user, monkeypatch, rewrite
):
    retrieve = AsyncMock(return_value=BELOW)
    monkeypatch.setattr("app.rag.retrieval.retrieve", retrieve)
    reformulator = Reformulator(db_session, admin_user, FakeLLM(reformulation=rewrite))

    outcome = await retrieve_gated(db_session, BODY, CTX, reformulate=reformulator)

    assert outcome.sufficient is False
    assert retrieve.await_count == 1
    assert (reformulator.attempts, reformulator.query) == (2, None)


async def test_a_first_attempt_that_clears_the_floor_never_reformulates(
    db_session, admin_user, monkeypatch
):
    monkeypatch.setattr("app.rag.retrieval.retrieve", AsyncMock(return_value=ABOVE))
    llm = FakeLLM(reformulation=REWRITE)
    reformulator = Reformulator(db_session, admin_user, llm)

    await retrieve_gated(db_session, BODY, CTX, reformulate=reformulator)

    assert llm.prompts == []
    assert reformulator.attempts == 1


# --- through the graph --------------------------------------------------------------


async def _graph_run(db_session, agent_saver, monkeypatch, retrieve_results, reformulation):
    """An email that meets every other auto-send condition: fully confident,
    worthy, non-clinical. Only grounding decides."""
    llm = FakeLLM(reformulation=reformulation)
    monkeypatch.setattr("app.services.email_service.get_llm", lambda: llm)
    retrieve = AsyncMock(side_effect=retrieve_results)
    monkeypatch.setattr("app.rag.retrieval.retrieve", retrieve)
    email, task = await seed_email(db_session, external_id="AAMk-retry")
    await agent_graph.start(task.id, email.id, None, AUTO, 0.95)
    snapshot = (
        await build_graph()
        .compile(checkpointer=agent_saver)
        .aget_state(run_config(thread_id("email", str(email.id))))
    )
    approvals = [
        r
        for r in (await db_session.execute(select(ApprovalRequest))).scalars().all()
        if r.payload.get("task_id") == str(task.id)
    ]
    return snapshot, approvals, task, retrieve


async def test_grounded_only_on_attempt_two_goes_to_approval_not_auto_send(
    db_session, agent_saver, monkeypatch, outlook
):
    snapshot, approvals, task, retrieve = await _graph_run(
        db_session, agent_saver, monkeypatch, [BELOW, ABOVE], REWRITE
    )

    values = snapshot.values
    assert values["grounded"] is True
    assert values["retrieval_attempts"] == 2
    assert values["reformulated_query"] == REWRITE
    assert values["retrieval_sufficient"] is True
    assert values["risk_tier"] == "high"
    assert snapshot.next == ("await_approval",)
    outlook.assert_not_awaited()
    (approval,) = approvals
    assert approval.payload["reasoning"]["reformulated_query"] == REWRITE
    assert approval.payload["reasoning"]["retrieval_attempts"] == 2


async def test_grounded_on_attempt_one_still_auto_sends(
    db_session, agent_saver, monkeypatch, outlook
):
    """The control: the retry changes nothing for a query that already clears
    the floor."""
    snapshot, approvals, _, retrieve = await _graph_run(
        db_session, agent_saver, monkeypatch, [ABOVE], REWRITE
    )

    assert snapshot.values["retrieval_attempts"] == 1
    assert snapshot.values["risk_tier"] == "low"
    assert snapshot.values["dispatch_result"] == "sent"
    assert approvals == []
    outlook.assert_awaited_once()
    assert retrieve.await_count == 1


async def test_both_attempts_failing_is_todays_ungrounded_fallback(
    db_session, agent_saver, monkeypatch, outlook
):
    snapshot, approvals, task, _ = await _graph_run(
        db_session, agent_saver, monkeypatch, [BELOW, BELOW], REWRITE
    )

    values = snapshot.values
    assert values["grounded"] is False
    assert values["retrieval_sufficient"] is False
    assert values["retrieval_attempts"] == 2
    assert values["draft_text"] == DRAFT
    assert snapshot.next == ("await_approval",)
    outlook.assert_not_awaited()
    (approval,) = approvals
    assert approval.payload["draft"] == DRAFT


async def test_flag_off_never_reformulates(client, front_desk_headers, db_session, monkeypatch):
    monkeypatch.setattr(settings, "agentic_pipeline_enabled", False)
    llm = FakeLLM(reformulation=REWRITE)
    monkeypatch.setattr("app.services.email_service.get_llm", lambda: llm)
    retrieve = AsyncMock(return_value=BELOW)
    monkeypatch.setattr("app.rag.retrieval.retrieve", retrieve)
    rewrite = AsyncMock(return_value=REWRITE)
    monkeypatch.setattr(Reformulator, "rewrite", rewrite)

    response = await client.post(
        "/api/v1/email/ingest",
        json={
            "sender": "patient@example.com",
            "recipient": "clinic@example.com",
            "subject": "Question",
            "body": BODY,
        },
        headers=front_desk_headers,
    )

    assert response.status_code == 201, response.text
    rewrite.assert_not_awaited()
    assert retrieve.await_count == 1
    assert not [p for p in llm.prompts if p.rstrip().endswith("QUERY:")]
    task = await db_session.get(Task, UUID(response.json()["task_id"]))
    await db_session.refresh(task)
    assert task.draft_text == DRAFT
