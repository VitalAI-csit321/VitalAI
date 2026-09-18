"""The agent graph: thread identity, run context, nodes, and how a run is invoked."""

import logging
from typing import Any
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.checkpointer import open_checkpointer
from app.agents.state import CaseState, Context
from app.models.user import User
from app.services import approval_service
from app.services.system_actor import get_or_create_agent_actor

logger = logging.getLogger(__name__)

# State fields copied into the approval payload so the reviewer sees why the
# agent proposed what it did.
_REASONING_FIELDS = (
    "intent",
    "triage_category",
    "triage_confidence",
    "retrieval_sufficient",
    "critic_verdict",
    "critic_reason",
)


def thread_id(channel: str, source_id: str) -> str:
    """One thread per inbound message, never per case.

    source_id is the channel's own row id (Email.id for email). An
    IntakeCase holds many messages (ingest_email reuses an existing case,
    Email.case_id is a non-unique FK). Keying threads on case_id would let a
    second email inherit the first one's draft and approval and collide with
    its pending resume.
    """
    return f"{channel}:{source_id}"


def run_config(tid: str) -> RunnableConfig:
    return {"configurable": {"thread_id": tid}}


async def make_context(session_factory: async_sessionmaker[AsyncSession]) -> Context:
    async with session_factory() as db:
        actor = await get_or_create_agent_actor(db)
    return Context(session_factory=session_factory, actor_id=actor.id)


async def create_approval(state: CaseState, runtime: Runtime[Context]) -> dict:
    """Write the ApprovalRequest (and its audit event). Runs exactly once.

    Kept apart from await_approval on purpose: interrupt() re-runs its whole
    node on resume, so a row written next to it would be written again on
    every resume. As its own node this one finishes its super-step and is
    checkpointed as done before the interrupt happens.
    """
    tid = thread_id(state["channel"], state["source_id"])
    async with runtime.context.session_factory() as db:
        actor = await db.get(User, runtime.context.actor_id)
        request = await approval_service.create_approval_request(
            db,
            # The existing approved-reply executor handles this action type,
            # including P1's draft_sent guard, so approval dispatches exactly
            # what the human approved.
            action_type="email.draft_reply",
            payload={
                "draft": state.get("draft_text"),
                "email_id": state["source_id"] if state["channel"] == "email" else None,
                "task_id": state.get("task_id"),
                "risk_tier": state.get("risk_tier"),
                "reasoning": {
                    k: v for k, v in state.items() if k in _REASONING_FIELDS and v is not None
                },
            },
            case_id=UUID(state["case_id"]) if state.get("case_id") else None,
            requested_by=actor,
            external_ref=tid,
        )
    return {"approval_request_id": str(request.id), "approval_status": request.status.value}


async def await_approval(state: CaseState) -> dict:
    """Pause until a human decides. Calls interrupt() and nothing else.

    This node re-runs from the top on resume, so it must stay free of side
    effects. It is the graph's ONLY interrupt node: a second one would leave
    threads with several pending interrupts, and LangGraph then refuses a
    plain Command(resume=...) ("When there are multiple pending interrupts,
    you must specify the interrupt id when resuming"). Adding one means
    switching every resume to interrupt-id-keyed resume values.
    """
    decision = interrupt({"approval_request_id": state["approval_request_id"]})
    update: dict = {"approval_status": "approved" if decision.get("approved") else "rejected"}
    if decision.get("draft") is not None:
        update["draft_text"] = decision["draft"]
    return update


def build_graph() -> StateGraph[CaseState, Context, CaseState, CaseState]:
    builder = StateGraph(CaseState, context_schema=Context)
    builder.add_node("create_approval", create_approval)
    builder.add_node("await_approval", await_approval)
    builder.add_edge(START, "create_approval")
    builder.add_edge("create_approval", "await_approval")
    # Approve and reject both end here for now: the send itself still runs
    # in the approvals route's executor. §4's dispatch node hangs off the
    # approved branch; a rejection must keep reaching END so no thread is
    # left paused forever.
    builder.add_edge("await_approval", END)
    return builder


async def run(tid: str, graph_input: CaseState | Command) -> dict[str, Any]:
    """Start or resume one thread against the Postgres checkpointer.

    durability="sync": each super-step's checkpoint is written before the
    next one starts, so create_approval is recorded as done before
    await_approval runs.
    """
    from app.database import AsyncSessionLocal

    async with open_checkpointer() as saver:
        graph = build_graph().compile(checkpointer=saver)
        return await graph.ainvoke(
            graph_input,
            run_config(tid),
            context=await make_context(AsyncSessionLocal),
            durability="sync",
        )


async def resume(tid: str, decision: dict) -> None:
    """BackgroundTasks entry point for an approve/reject decision."""
    try:
        await run(tid, Command(resume=decision))
    except Exception:
        # A background task's exception goes nowhere. The approval row is
        # already decided and is what the queue shows; the thread stays
        # paused and this log line is the only trace until §4.1's failure
        # path (audit event + Task) lands.
        logger.exception("Agent graph resume failed for thread %s", tid)
