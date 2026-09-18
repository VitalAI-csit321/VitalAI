"""Postgres checkpointer for the agent graph.

Same database as the app, different driver: the app talks asyncpg through
SQLAlchemy, AsyncPostgresSaver talks psycopg3 directly. Checkpoint writes
therefore commit in a different transaction from any node's business
write, which is why nodes with side effects must be safe to re-run.

The checkpointer's tables belong to LangGraph, not to Alembic. setup()
creates them from lifespan (app/main.py) when the agentic pipeline is on.
Never add them to a migration: a langgraph upgrade can change that schema
and would then collide with our migration head.
"""

from contextlib import AbstractAsyncContextManager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy.engine import make_url

from app.config import settings


def conninfo(database_url: str) -> str:
    """The app's SQLAlchemy URL rewritten as a plain libpq URL for psycopg."""
    return make_url(database_url).set(drivername="postgresql").render_as_string(hide_password=False)


def open_checkpointer() -> AbstractAsyncContextManager[AsyncPostgresSaver]:
    """One connection for the lifetime of one graph run.

    from_conn_string builds it with autocommit=True, prepare_threshold=0 and
    row_factory=dict_row, all three of which the saver requires. The run
    releases it when it reaches END or pauses at interrupt(), so nothing is
    held open while a human decides.
    """
    # ponytail: a connection per run, fine while graph runs are serialised
    # (P3's Semaphore(1)). Move to a shared psycopg_pool.AsyncConnectionPool
    # opened in lifespan, with the same three kwargs, if runs go concurrent.
    return AsyncPostgresSaver.from_conn_string(conninfo(settings.database_url))
