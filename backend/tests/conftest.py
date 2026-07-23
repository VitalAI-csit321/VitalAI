"""Test fixtures.

Uses DATABASE_URL from the environment — defaults to SQLite in-memory for local dev,
Postgres in CI (where DATABASE_URL is set to the service container).

FR-RAG-01 (vector/chunks retrieval) is the exception: SQLite has no pgvector, no
cosine_distance, no HNSW, no SET LOCAL GUCs. Anything exercising app.rag.retrieval
uses the `pg_session` / `seeded_chunks` fixtures below instead, which talk to a real
Postgres+pgvector database (the docker-compose `db` service, migrated to head).
"""

import asyncio
import os
from datetime import date
from pathlib import Path

import pytest_asyncio
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command

_DB_URL = os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")

from app.auth.security import create_access_token, hash_password  # noqa: E402
from app.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Patient, User, UserRole  # noqa: E402
from app.models.patient import Gender, PatientStatus  # noqa: E402
from scripts.seed_synthetic_chunks import seed as seed_synthetic_corpus  # noqa: E402

# Real Postgres+pgvector database for chunk/retrieval tests — never SQLite.
# Defaults to the docker-compose `db` service exposed on localhost:5432 (the
# same DATABASE_URL used to run `alembic upgrade head` and the seed script).
_PG_TEST_URL = os.environ.get(
    "RAG_TEST_DATABASE_URL",
    "postgresql+asyncpg://vitalai:vitalai@localhost:5432/vitalai",
)

_ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def _alembic_upgrade_head() -> None:
    """Run off the event loop: alembic/env.py drives migrations with its own
    asyncio.run(), which cannot be called from a loop that's already running.
    Upgrading to head is idempotent (tracked via the alembic_version table),
    so this is safe to call whether or not CI's separate "Run migrations"
    step, or another fixture, already brought the database to head.
    """
    command.upgrade(Config(str(_ALEMBIC_INI)), "head")


@pytest_asyncio.fixture
async def test_engine():
    engine = create_async_engine(_DB_URL, echo=False)
    if engine.dialect.name == "postgresql":
        # Alembic migrations are the single source of truth for the Postgres
        # schema, including the audit_events_no_update/_no_delete triggers
        # from migration 0001. Those live in raw trigger DDL that
        # Base.metadata knows nothing about, so create_all can't produce them.
        # Idempotent (tracked via alembic_version), safe to call every test.
        #
        # Schema is never dropped here: this is the same live database the
        # pg_session/seeded_chunks (RAG) and test_audit_trigger.py fixtures
        # use for the whole test session. Per-test isolation instead comes
        # from db_session/client below (transaction + rollback, the same
        # pattern pg_session already uses) rather than tearing down schema
        # those other fixtures depend on staying put.
        await asyncio.to_thread(_alembic_upgrade_head)
    else:
        # Migrations use Postgres-only SQL (JSONB, pgvector, raw trigger DDL)
        # and cannot run against SQLite, so SQLite keeps building schema
        # straight from the models. Each test gets its own fresh in-memory
        # engine, so create_all/drop_all is sufficient isolation here.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    yield engine
    if engine.dialect.name != "postgresql":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine):
    if test_engine.dialect.name == "postgresql":
        # Savepoint-based isolation, mirroring pg_session: the outer
        # transaction rolls back everything the test wrote, including any
        # internal session.commit() calls, which only release a savepoint,
        # so the shared dev database is left exactly as it was.
        async with test_engine.connect() as conn:
            trans = await conn.begin()
            async_session = async_sessionmaker(
                bind=conn,
                class_=AsyncSession,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            async with async_session() as session:
                yield session
            await trans.rollback()
    else:
        async_session = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with async_session() as session:
            yield session


@pytest_asyncio.fixture
async def patient(db_session: AsyncSession) -> Patient:
    p = Patient(
        mrn="MRN-TESTFIX01",
        name="Test Fixture Patient",
        dob=date(1990, 1, 1),
        gender=Gender.FEMALE,
        status=PatientStatus.ACTIVE,
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest_asyncio.fixture
async def client(db_session):
    # Reuses db_session's own connection/transaction for every request
    # instead of opening a fresh session per call. Required so data written
    # via db_session (or an earlier request) is visible to routes that query
    # the DB, e.g. get_current_user's db.get(User, ...) lookup, since on
    # Postgres a separate session would sit outside this test's savepoint
    # and see none of it.
    async def override_get_db():
        yield db_session

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


@pytest_asyncio.fixture
async def operator_user(db_session: AsyncSession) -> User:
    user = User(
        email="operator@example.com",
        hashed_password=hash_password("password123"),
        full_name="Operator Tester",
        role=UserRole.OPERATOR,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def doctor_user(db_session: AsyncSession) -> User:
    user = User(
        email="doctor@example.com",
        hashed_password=hash_password("password123"),
        full_name="Doctor Tester",
        role=UserRole.DOCTOR,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
def operator_headers(operator_user: User) -> dict[str, str]:
    token = create_access_token(operator_user.id, operator_user.role)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
def doctor_headers(doctor_user: User) -> dict[str, str]:
    token = create_access_token(doctor_user.id, doctor_user.role)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def pg_session():
    """A session bound to a real Postgres+pgvector connection.

    Wraps each test in an outer transaction + SAVEPOINT
    (join_transaction_mode="create_savepoint") so app.rag.retrieval's internal
    session.commit() (for the GOV-RETRIEVE audit event) only releases the
    savepoint — the outer rollback below discards everything the test wrote,
    including seeded chunks, leaving the dev database as it was.
    """
    engine = create_async_engine(_PG_TEST_URL, echo=False)
    async with engine.connect() as conn:
        trans = await conn.begin()
        async_session = async_sessionmaker(
            bind=conn,
            class_=AsyncSession,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        async with async_session() as session:
            yield session
        await trans.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_chunks(pg_session: AsyncSession) -> AsyncSession:
    """pg_session pre-loaded with the FR-RAG-01 synthetic corpus (scripts/synthetic_corpus)."""
    await seed_synthetic_corpus(pg_session)
    return pg_session
