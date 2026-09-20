"""Graph core (build spec §2): state, per-node sessions, checkpointer, flag."""

import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select

from app.agents.checkpointer import conninfo
from app.agents.graph import make_context, run_config, thread_id
from app.config import Settings, settings
from app.models.user import User
from app.services.system_actor import AGENT_EMAIL
from tests.agent_xproc_worker import build_noop_graph

_BACKEND = Path(__file__).resolve().parent.parent
_ON_POSTGRES = os.environ["DATABASE_URL"].startswith("postgresql")


def test_flag_defaults_off():
    # The declared default, not Settings(): the suite is also run with
    # AGENTIC_PIPELINE_ENABLED=true in the environment.
    assert Settings.model_fields["agentic_pipeline_enabled"].default is False


def test_thread_id_is_channel_and_source_id_not_case_id():
    assert thread_id("email", "abc-123") == "email:abc-123"


def test_conninfo_strips_the_asyncpg_driver():
    assert (
        conninfo("postgresql+asyncpg://u:p%40ss@db:5432/vitalai")
        == "postgresql://u:p%40ss@db:5432/vitalai"
    )


async def test_context_carries_the_seeded_agent_actor(detached_sessionmaker, db_session):
    ctx = await make_context(detached_sessionmaker)

    actor = (await db_session.execute(select(User).where(User.email == AGENT_EMAIL))).scalar_one()
    assert ctx.actor_id == actor.id
    assert ctx.session_factory is detached_sessionmaker


async def test_two_node_path_opens_a_session_per_node_and_checkpoints_no_context(
    detached_sessionmaker,
):
    saver = InMemorySaver()
    graph = build_noop_graph().compile(checkpointer=saver)
    config = run_config(thread_id("email", str(uuid4())))

    result = await graph.ainvoke(
        {"channel": "email", "source_id": "x"},
        config,
        context=await make_context(detached_sessionmaker),
    )

    # Each node ran against its own session and saw the agent actor row.
    assert result["audit_refs"] == ["first", "second"]
    checkpoint = await saver.aget_tuple(config)
    assert checkpoint is not None
    # Context (the session factory) is invoke-time only, never persisted.
    stored = checkpoint.checkpoint["channel_values"]
    assert "session_factory" not in stored
    assert set(stored) <= {"channel", "source_id", "audit_refs"}


async def test_lifespan_sets_up_checkpointer_only_when_flag_on(monkeypatch):
    from app import main

    calls = []

    class FakeSaver:
        async def setup(self):
            calls.append("setup")

    class FakeCm:
        async def __aenter__(self):
            return FakeSaver()

        async def __aexit__(self, *exc):
            return False

    async def no_hydrate(db):
        return None

    monkeypatch.setattr("app.services.settings_service.hydrate", no_hydrate)
    monkeypatch.setattr("app.agents.checkpointer.open_checkpointer", lambda: FakeCm())

    monkeypatch.setattr(settings, "agentic_pipeline_enabled", False)
    async with main.lifespan(main.app):
        pass
    assert calls == []

    monkeypatch.setattr(settings, "agentic_pipeline_enabled", True)
    async with main.lifespan(main.app):
        pass
    assert calls == ["setup"]


@pytest.mark.skipif(not _ON_POSTGRES, reason="AsyncPostgresSaver needs Postgres")
async def test_checkpoint_persists_to_postgres_and_resumes_in_another_process():
    """A real second interpreter picks the thread up from Postgres.

    Writes only checkpointer rows under a throwaway thread and deletes them
    afterwards, so it is safe on the shared dev database.
    """
    from app.agents.checkpointer import open_checkpointer

    tid = thread_id("test", str(uuid4()))
    try:
        await _worker("noop-start", tid)
        async with open_checkpointer() as saver:
            paused = await saver.aget_tuple(run_config(tid))
        assert paused is not None
        assert paused.checkpoint["channel_values"]["audit_refs"] == ["first"]

        await _worker("noop-resume", tid)
        async with open_checkpointer() as saver:
            done = await saver.aget_tuple(run_config(tid))
        assert done.checkpoint["channel_values"]["audit_refs"] == ["first", "second"]
    finally:
        async with open_checkpointer() as saver:
            await saver.adelete_thread(tid)


async def _worker(*args: str) -> str:
    """Run tests/agent_xproc_worker.py as a separate OS process."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "tests.agent_xproc_worker",
        *args,
        cwd=_BACKEND,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    assert proc.returncode == 0, err.decode()
    return out.decode().strip()


async def test_a_node_failure_keeps_the_exception_detail_out_of_the_staff_note(
    db_session, front_desk_user
):
    """The staff-visible note must name the stage, not quote the exception.

    app.llm.guardrail states the rule for InputBlockedError: never put
    matched_pattern or str(exc) where it can be read back. record_agent_failure
    copied the raw error into Task.handover_context, which the inbox API
    returns and the Inbox renders, so a blocked draft told staff exactly which
    injection phrase matched. The same leak applies to any exception that
    carries a connection string, a URL with a token, or a row of patient data.

    The audit event keeps the full detail: that record is privileged.
    """
    from sqlalchemy import select

    from app.models.audit import AuditEvent
    from app.models.case import IntakeCase, IntakeStatus
    from app.models.task import Task
    from app.services import task_service

    case = IntakeCase(
        contact_reason="Question", contact_channel="email", status=IntakeStatus.RECEIVED
    )
    db_session.add(case)
    await db_session.flush()

    secret = "Input blocked: matched pattern 'ignore previous instructions'"
    await task_service.record_agent_failure(
        db_session,
        task_id=None,
        case_id=case.id,
        actor=front_desk_user,
        stage="draft",
        error_type="InputBlockedError",
        error_detail=secret,
    )

    task = (await db_session.execute(select(Task).where(Task.case_id == case.id))).scalars().first()
    assert task is not None
    assert task.handover_context is not None
    assert "draft" in task.handover_context
    # The type name stays: staff need to tell an injection block from an
    # outage. The message never does, because that is what carries the
    # matched pattern.
    assert "InputBlockedError" in task.handover_context
    assert "ignore previous instructions" not in task.handover_context
    assert secret not in task.handover_context

    event = (
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.case_id == case.id, AuditEvent.action == "agent.node_failed"
                )
            )
        )
        .scalars()
        .first()
    )
    assert event is not None
    assert "ignore previous instructions" in event.details["error"]
