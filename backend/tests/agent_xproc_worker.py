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


async def main(argv: list[str]) -> None:
    cmd, tid = argv[0], argv[1]
    if cmd == "noop-start":
        await _noop_run(tid, {"channel": "test", "source_id": tid})
    elif cmd == "noop-resume":
        await _noop_run(tid, None)
    else:
        raise SystemExit(f"unknown command {cmd}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
