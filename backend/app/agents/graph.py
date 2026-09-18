"""The agent graph: thread identity, run context, and how a run is invoked."""

from langchain_core.runnables import RunnableConfig
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.state import Context
from app.services.system_actor import get_or_create_agent_actor


def thread_id(channel: str, source_id: str) -> str:
    """One thread per inbound message, never per case.

    An IntakeCase holds many messages (ingest_email reuses an existing case,
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
