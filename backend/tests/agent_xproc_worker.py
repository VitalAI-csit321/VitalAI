"""Second-process half of the cross-process graph tests.

In-process resume proves nothing: the graph object, the saver and the event
loop are all still in memory. The tests launch this module as a separate
interpreter (`python -m tests.agent_xproc_worker ...`) so the only thing the
two sides share is Postgres.
"""

import asyncio
import sys

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.agents.state import CaseState, Context
from app.models.user import User


def _noop(name: str):
    async def node(state: CaseState, runtime: Runtime[Context]) -> dict:
        async with runtime.context.session_factory() as db:
            assert await db.get(User, runtime.context.actor_id) is not None
        return {"audit_refs": [*state.get("audit_refs", []), name]}

    return node


def build_noop_graph() -> StateGraph:
    builder = StateGraph(CaseState, context_schema=Context)
    builder.add_node("first", _noop("first"))
    builder.add_node("second", _noop("second"))
    builder.add_edge(START, "first")
    builder.add_edge("first", "second")
    builder.add_edge("second", END)
    return builder


async def _noop_run(tid: str, graph_input) -> None:
    from app.agents.checkpointer import open_checkpointer
    from app.agents.graph import make_context, run_config
    from app.database import AsyncSessionLocal

    async with open_checkpointer() as saver:
        await saver.setup()
        graph = build_noop_graph().compile(checkpointer=saver, interrupt_before=["second"])
        await graph.ainvoke(
            graph_input,
            run_config(tid),
            context=await make_context(AsyncSessionLocal),
            durability="sync",
        )


async def _approval_start(tid: str) -> None:
    """Run the real graph until it pauses."""
    from app.agents import graph
    from app.agents.checkpointer import open_checkpointer

    async with open_checkpointer() as saver:
        await saver.setup()
    channel, source_id = tid.split(":", 1)
    result = await graph.run(
        tid,
        {"channel": channel, "source_id": source_id, "draft_text": "Cross-process draft."},
    )
    assert "__interrupt__" in result, result


async def _approval_decide(tid: str, approval_id: str, decision: str) -> None:
    """What a restarted server does: decide the row, then resume the thread
    through the same function the approvals route schedules."""
    from uuid import UUID

    from app.agents import graph
    from app.database import AsyncSessionLocal
    from app.models.user import UserRole
    from app.services import approval_service
    from app.services.system_actor import get_or_create_system_actor

    async with AsyncSessionLocal() as db:
        human = await get_or_create_system_actor(
            db, "xproc-approver@test.vitalai.internal", "XProc Approver", UserRole.ADMIN
        )
        if decision == "approve":
            await approval_service.approve(db, UUID(approval_id), human)
        else:
            await approval_service.reject(db, UUID(approval_id), human)
    await graph.resume(tid, {"approved": decision == "approve"})


async def main(argv: list[str]) -> None:
    cmd, tid = argv[0], argv[1]
    if cmd == "noop-start":
        await _noop_run(tid, {"channel": "test", "source_id": tid})
    elif cmd == "noop-resume":
        await _noop_run(tid, None)
    elif cmd == "approval-start":
        await _approval_start(tid)
    elif cmd == "approval-decide":
        await _approval_decide(tid, argv[2], argv[3])
    else:
        raise SystemExit(f"unknown command {cmd}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
