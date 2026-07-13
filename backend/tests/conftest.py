"""Test fixtures.

Uses DATABASE_URL from the environment — defaults to SQLite in-memory for local dev,
Postgres in CI (where DATABASE_URL is set to the service container).
"""

import asyncio
import os
from pathlib import Path

import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_DB_URL = os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")

from app.auth.security import create_access_token, hash_password  # noqa: E402
from app.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, User, UserRole  # noqa: E402

_ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def _alembic_upgrade_head() -> None:
    """Run off the event loop: alembic/env.py drives migrations with its own
    asyncio.run(), which cannot be called from a loop that's already running.
    Upgrading to head is idempotent (tracked via the alembic_version table),
    so this is safe to call whether or not CI's separate "Run migrations"
    step — or another fixture — already brought the database to head.
    """
    command.upgrade(Config(str(_ALEMBIC_INI)), "head")


@pytest_asyncio.fixture
async def test_engine():
    engine = create_async_engine(_DB_URL, echo=False)
    if engine.dialect.name == "postgresql":
        # Alembic migrations are the single source of truth for the Postgres
        # schema, including the audit_events_no_update/_no_delete triggers
        # from migration 0001 — those live in raw trigger DDL that
        # Base.metadata knows nothing about, so create_all can't produce them.
        await asyncio.to_thread(_alembic_upgrade_head)
    else:
        # Migrations use Postgres-only SQL (JSONB, pgvector, raw trigger DDL)
        # and cannot run against SQLite, so SQLite keeps building schema
        # straight from the models.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
        else:
            await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine):
    async_session = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session


@pytest_asyncio.fixture
async def client(test_engine):
    async_session = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    user = User(
        email="admin@example.com",
        hashed_password=hash_password("password123"),
        full_name="Admin Tester",
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def front_desk_user(db_session: AsyncSession) -> User:
    user = User(
        email="frontdesk@example.com",
        hashed_password=hash_password("password123"),
        full_name="Front Desk Tester",
        role=UserRole.FRONT_DESK,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
def admin_headers(admin_user: User) -> dict[str, str]:
    token = create_access_token(admin_user.id, admin_user.role)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
def front_desk_headers(front_desk_user: User) -> dict[str, str]:
    token = create_access_token(front_desk_user.id, front_desk_user.role)
    return {"Authorization": f"Bearer {token}"}
