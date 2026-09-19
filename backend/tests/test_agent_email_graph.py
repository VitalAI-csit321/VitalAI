"""The email reply pipeline as a graph (build spec §4).

Node tests call one node with a hand-built state and check the partial update
it returns; none depends on another node. The end-to-end tests go through the
real ingest route with the flag on, and compare against the flag-off path on
the same input.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select

from app.agents import graph as agent_graph
from app.agents import nodes
from app.agents.graph import build_graph, make_context, route_intent, run_config, thread_id
from app.config import settings
from app.models.approval import ApprovalRequest, ApprovalStatus
from app.models.audit import AuditEvent
from app.models.task import Task, TaskCategory, TaskItemStatus, TaskPriority
from app.services import outlook_sync_service
from app.services.outlook_auth import OutlookAuthRequiredError
from tests.agent_fakes import DRAFT, FakeLLM, graph_input, seed_email

BODY = "What time do you open on Saturdays?"


@pytest.fixture
def llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr("app.services.email_service.get_llm", lambda: fake)
    monkeypatch.setattr("app.rag.retrieval.retrieve", AsyncMock(return_value=[]))
    return fake


@pytest.fixture
def outlook(monkeypatch):
    """Outlook on, every send mocked and counted. Nothing leaves the test."""
    monkeypatch.setattr(settings, "outlook_enabled", True)
    monkeypatch.setattr("app.services.outlook_auth.get_access_token", AsyncMock(return_value="t"))
    sends = AsyncMock(return_value=None)
    monkeypatch.setattr("app.services.outlook_client.send_reply", sends)
    return sends


async def _runtime(detached_sessionmaker):
    return SimpleNamespace(context=await make_context(detached_sessionmaker))


async def _approvals(db_session, task) -> list[ApprovalRequest]:
    rows = (await db_session.execute(select(ApprovalRequest))).scalars().all()
    return [r for r in rows if r.payload.get("task_id") == str(task.id)]


async def _thread(saver, email_id) -> dict:
    snapshot = (
        await build_graph()
        .compile(checkpointer=saver)
        .aget_state(run_config(thread_id("email", str(email_id))))
    )
    return {"values": snapshot.values, "next": snapshot.next, "interrupts": snapshot.interrupts}


async def _ingest(client, headers, **extra) -> tuple[UUID, UUID]:
    response = await client.post(
        "/api/v1/email/ingest",
        json={
            "sender": "patient@example.com",
            "recipient": "clinic@example.com",
            "subject": "Question",
            "body": BODY,
            **extra,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["task_id"]), UUID(response.json()["email"]["id"])


# --- nodes, one at a time ------------------------------------------------------


async def test_load_populates_state_from_the_ingested_rows(detached_sessionmaker, db_session):
    email, task = await seed_email(db_session)

    update = await nodes.load(graph_input(email, task), await _runtime(detached_sessionmaker))

    assert update["case_id"] == str(email.case_id)
    assert update["intent"] == "general_administrative"
    assert update["content"] == BODY
    assert update["patient_id"] is None


async def test_consent_without_a_record_reads_none_and_does_not_block(
    detached_sessionmaker, db_session
):
    email, _ = await seed_email(db_session)

    update = await nodes.consent(
        {"case_id": str(email.case_id)}, await _runtime(detached_sessionmaker)
    )

    assert update == {"consent_status": "none"}


@pytest.mark.parametrize(
    ("intent", "outcome", "expected"),
    [
        # No agent, no draft, at any confidence and whatever the gate said.
        ("urgent_emergency", "auto_routed", "human_review"),
        ("complaint_escalation", "auto_routed", "human_review"),
        ("general_administrative", "human_review", "human_review"),
        # Placeholder edges until §9-§12 build these agents.
        ("appointment_request", "auto_routed", "booking"),
        ("medical_records_request", "auto_routed", "records"),
        ("prescription_renewal", "auto_routed", "prescription"),
        ("new_patient_onboarding", "auto_routed", "onboarding"),
        ("results_enquiry", "auto_routed_flagged", "retrieval"),
        ("billing_insurance_enquiry", "auto_routed", "retrieval"),
    ],
)
def test_route_intent(intent, outcome, expected):
    assert route_intent({"intent": intent, "routing_outcome": outcome}) == expected


async def test_reply_gate_parks_a_not_worthy_email(detached_sessionmaker, db_session, llm):
    llm.worthy = False
    email, task = await seed_email(db_session)

    update = await nodes.reply_gate(graph_input(email, task), await _runtime(detached_sessionmaker))

    assert update == {"reply_verdict": "not_worthy", "dispatch_result": "not_worthy"}
    await db_session.refresh(task)
    assert task.priority == TaskPriority.LOW
    assert task.handover_context == "test verdict"


async def test_draft_returns_text_and_grounding(detached_sessionmaker, db_session, llm):
    email, task = await seed_email(db_session)

    update = await nodes.draft(graph_input(email, task), await _runtime(detached_sessionmaker))

    assert update == {"draft_text": DRAFT, "grounded": False}


async def test_guardrail_blocks_a_restricted_draft(detached_sessionmaker, db_session):
    email, task = await seed_email(db_session)
    state = {**graph_input(email, task), "draft_text": "This is an emergency, go to hospital."}

    update = await nodes.guardrail(state, await _runtime(detached_sessionmaker))

    assert update == {"dispatch_result": "blocked"}


async def test_risk_is_the_existing_three_bucket_step_function():
    assert await nodes.risk({}) == {"risk_score": 10, "risk_tier": "low"}


async def test_auto_send_delivers_through_the_shared_function(
    detached_sessionmaker, db_session, outlook
):
    email, task = await seed_email(db_session, external_id="AAMk-node")
    state = {**graph_input(email, task), "draft_text": DRAFT}

    update = await nodes.auto_send(state, await _runtime(detached_sessionmaker))

    assert update == {"dispatch_result": "sent", "delivery_error": None}
    outlook.assert_awaited_once_with("t", "AAMk-node", DRAFT)
    await db_session.refresh(task)
    assert task.draft_sent is True


async def test_auto_send_failure_returns_the_reason_and_leaves_task_unsent(
    detached_sessionmaker, db_session, outlook
):
    outlook.side_effect = httpx.ConnectError("graph down")
    email, task = await seed_email(db_session, external_id="AAMk-node")
    state = {**graph_input(email, task), "draft_text": DRAFT}

    update = await nodes.auto_send(state, await _runtime(detached_sessionmaker))

    assert "graph down" in update["delivery_error"]
    await db_session.refresh(task)
    assert task.draft_sent is False


async def test_dispatch_reads_draft_sent_and_never_sends(
    detached_sessionmaker, db_session, outlook
):
    email, task = await seed_email(db_session)
    task.draft_sent = True
    await db_session.commit()

    update = await nodes.dispatch(graph_input(email, task), await _runtime(detached_sessionmaker))

    assert update == {"dispatch_result": "sent"}
    outlook.assert_not_awaited()


async def test_dispatch_records_a_failed_delivery_on_the_task(detached_sessionmaker, db_session):
    email, task = await seed_email(db_session)
    state = {**graph_input(email, task), "delivery_error": "Outlook said no"}

    update = await nodes.dispatch(state, await _runtime(detached_sessionmaker))

    assert update == {"dispatch_result": "send_failed"}
    await db_session.refresh(task)
    assert "Outlook said no" in task.handover_context
    assert task.draft_sent is False


# --- whole graph ---------------------------------------------------------------


async def test_a_node_that_raises_leaves_a_visible_task_and_an_audit_event(
    db_session, agent_saver, llm, monkeypatch
):
    """§4.1: a background run swallows exceptions, so the failure path is the
    only thing that stops a case vanishing."""
    email, task = await seed_email(db_session)
    monkeypatch.setattr(
        "app.services.email_service.generate_draft", AsyncMock(side_effect=RuntimeError("down"))
    )

    await agent_graph.start(task.id, email.id, None, _gate("auto_routed"), 0.95)

    thread = await _thread(agent_saver, email.id)
    assert thread["next"] == ()
    assert thread["values"]["error"] == "draft: RuntimeError"
    await db_session.refresh(task)
    assert "draft" in task.handover_context
    assert await _approvals(db_session, task) == []
    events = (
        (await db_session.execute(select(AuditEvent).where(AuditEvent.case_id == email.case_id)))
        .scalars()
        .all()
    )
    assert "agent.node_failed" in [e.action for e in events]


def _gate(outcome: str):
    from app.services.task_routing_gate import TaskRoutingGateResult, TaskRoutingOutcome

    return TaskRoutingGateResult(outcome=TaskRoutingOutcome(outcome), override_reason=None)


async def test_flag_on_email_pauses_then_approve_sends_once_and_reaches_end(
    client, front_desk_headers, admin_headers, db_session, agent_saver, llm, outlook, monkeypatch
):
    """Gate (b), (f) and (i). An ungrounded draft fails the auto-send predicate,
    so the run pauses carrying the draft; the case has no consent record and
    that must not matter."""
    monkeypatch.setattr(settings, "agentic_pipeline_enabled", True)
    task_id, email_id = await _ingest(
        client, front_desk_headers, external_id="AAMk-e2e", external_source="outlook"
    )

    paused = await _thread(agent_saver, email_id)
    assert paused["next"] == ("await_approval",)
    assert paused["values"]["consent_status"] == "none"
    assert "error" not in paused["values"]
    task = await db_session.get(Task, task_id)
    await db_session.refresh(task)
    (approval,) = await _approvals(db_session, task)
    assert approval.payload["draft"] == DRAFT
    assert approval.external_ref == thread_id("email", str(email_id))
    assert task.draft_approval_id == approval.id
    assert task.draft_text == DRAFT
    outlook.assert_not_awaited()

    response = await client.post(
        f"/api/v1/approvals/{approval.id}/approve", json={}, headers=admin_headers
    )

    assert response.status_code == 200, response.text
    outlook.assert_awaited_once_with("t", "AAMk-e2e", DRAFT)
    done = await _thread(agent_saver, email_id)
    assert done["next"] == ()
    assert done["values"]["dispatch_result"] == "sent"
    assert len(await _approvals(db_session, task)) == 1
    await db_session.refresh(task)
    assert task.draft_sent is True


@pytest.mark.parametrize("should_send", [True, False], ids=["auto_sends", "needs_approval"])
async def test_flag_on_and_off_make_the_same_auto_send_decision(
    client, front_desk_headers, db_session, agent_saver, llm, outlook, monkeypatch, should_send
):
    """Gate (c) and (d): same input, both paths, same decision, and an
    auto-send actually delivers exactly once on either path."""
    if should_send:
        monkeypatch.setattr(
            "app.services.email_service._generate_org_grounded_reply",
            AsyncMock(return_value=(DRAFT, True)),
        )

    results = {}
    for flag in (False, True):
        monkeypatch.setattr(settings, "agentic_pipeline_enabled", flag)
        outlook.reset_mock()
        task_id, _ = await _ingest(
            client, front_desk_headers, external_id=f"AAMk-{flag}", external_source="outlook"
        )
        task = await db_session.get(Task, task_id)
        await db_session.refresh(task)
        results[flag] = (
            task.draft_sent,
            task.draft_text,
            len(await _approvals(db_session, task)),
            outlook.await_count,
        )

    assert results[True] == results[False]
    assert results[True] == ((True, DRAFT, 0, 1) if should_send else (False, DRAFT, 1, 0))


@pytest.mark.parametrize("flag", [False, True], ids=["flag_off", "flag_on"])
async def test_urgent_category_without_keyword_is_never_drafted(
    client, front_desk_headers, db_session, agent_saver, llm, monkeypatch, flag
):
    """Gate (e)."""
    monkeypatch.setattr(settings, "agentic_pipeline_enabled", flag)
    llm.category = "urgent_emergency"
    drafted = []
    monkeypatch.setattr(
        "app.services.email_service.generate_draft",
        AsyncMock(side_effect=lambda *a, **k: drafted.append(a) or (DRAFT, True)),
    )

    response = await client.post(
        "/api/v1/email/ingest",
        json={
            "sender": "patient@example.com",
            "recipient": "clinic@example.com",
            "subject": "Question",
            "body": "Please call me back today.",
        },
        headers=front_desk_headers,
    )

    assert response.json()["outcome"] == "human_review"
    assert response.json()["override_reason"] == "urgent_category"
    assert drafted == []
    task = await db_session.get(Task, UUID(response.json()["task_id"]))
    assert task.category == TaskCategory.URGENT_EMERGENCY
    assert await _approvals(db_session, task) == []
    if flag:
        done = await _thread(agent_saver, response.json()["email"]["id"])
        assert done["next"] == ()
        assert "draft_text" not in done["values"]


async def test_failed_auto_send_on_the_graph_falls_back_to_a_paused_approval(
    client, front_desk_headers, db_session, agent_saver, llm, outlook, monkeypatch
):
    """Gate (d), graph side: the draft reaches the human queue with the reason."""
    monkeypatch.setattr(settings, "agentic_pipeline_enabled", True)
    monkeypatch.setattr(
        "app.services.email_service._generate_org_grounded_reply",
        AsyncMock(return_value=(DRAFT, True)),
    )
    outlook.side_effect = httpx.ConnectError("graph down")

    task_id, email_id = await _ingest(
        client, front_desk_headers, external_id="AAMk-fail", external_source="outlook"
    )

    outlook.assert_awaited_once()
    paused = await _thread(agent_saver, email_id)
    assert paused["next"] == ("await_approval",)
    task = await db_session.get(Task, task_id)
    await db_session.refresh(task)
    assert task.draft_sent is False
    (approval,) = await _approvals(db_session, task)
    assert "graph down" in approval.payload["delivery_error"]
    assert task.draft_approval_id == approval.id


@pytest.mark.parametrize(
    ("failure", "status"),
    [(httpx.ConnectError("graph down"), 502), (OutlookAuthRequiredError("signed out"), 503)],
    ids=["send_error", "auth_required"],
)
async def test_failed_approved_send_still_resumes_the_thread_to_end(
    client,
    front_desk_headers,
    admin_headers,
    db_session,
    agent_saver,
    llm,
    outlook,
    monkeypatch,
    failure,
    status,
):
    """Gate (g), spec §4.1a. The route raises, so BackgroundTasks never run;
    the resume has to be scheduled some other way or the thread sits paused
    behind an APPROVED row that cannot be re-approved."""
    monkeypatch.setattr(settings, "agentic_pipeline_enabled", True)
    task_id, email_id = await _ingest(
        client, front_desk_headers, external_id="AAMk-502", external_source="outlook"
    )
    task = await db_session.get(Task, task_id)
    (approval,) = await _approvals(db_session, task)
    if isinstance(failure, OutlookAuthRequiredError):
        monkeypatch.setattr(
            "app.services.outlook_auth.get_access_token", AsyncMock(side_effect=failure)
        )
    else:
        outlook.side_effect = failure

    response = await client.post(
        f"/api/v1/approvals/{approval.id}/approve", json={}, headers=admin_headers
    )
    # The caller's response is unchanged.
    assert response.status_code == status
    while outlook_sync_service._drafting:
        await asyncio.gather(*outlook_sync_service._drafting)

    done = await _thread(agent_saver, email_id)
    assert done["next"] == ()
    assert not done["interrupts"]
    assert done["values"]["dispatch_result"] == "send_failed"
    await db_session.refresh(task)
    assert task.draft_sent is False
    assert task.status == TaskItemStatus.PENDING
    assert "not delivered" in task.handover_context
    await db_session.refresh(approval)
    assert approval.status == ApprovalStatus.APPROVED
    # A second approve is refused, which is why the resume cannot wait for one.
    again = await client.post(
        f"/api/v1/approvals/{approval.id}/approve", json={}, headers=admin_headers
    )
    assert again.status_code == 409
