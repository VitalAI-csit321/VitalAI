from datetime import datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, DateTime, Integer, LargeBinary, Text, Uuid
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


@compiles(Computed, "sqlite")
def _skip_computed_on_sqlite(element: Computed, compiler, **kw) -> str:
    """SQLite has no to_tsvector; render no GENERATED ALWAYS clause at all so
    SQLite gets a plain nullable column instead. Full-text search only ever
    runs against the real Postgres fixture (see tests/conftest.py::pg_session),
    same reasoning as _embedding's SQLite variant below. Global by class
    (Computed, not this specific column) since nothing else in this codebase
    uses Computed() today, and any future Postgres-only generated column would
    want the same "inert under SQLite" behaviour."""
    return ""


# postgresql.UUID with_variant Uuid() so SQLite (other suites' in-memory tests) still compiles
_pg_uuid = postgresql.UUID(as_uuid=True).with_variant(Uuid(), "sqlite")
# vector(512) has no SQLite equivalent; substitute an opaque blob so
# Base.metadata.create_all does not blow up for unrelated SQLite-backed test suites.
# Vector similarity queries against this column only run under the real Postgres
# fixture (see tests/conftest.py::pg_session).
_embedding = Vector(512).with_variant(LargeBinary(), "sqlite")
# Postgres: a real GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
# column (Postgres computes/maintains it on every insert; the Computed() marker
# below tells SQLAlchemy's ORM to never include it in an INSERT/UPDATE itself --
# omitting the marker still put it in the VALUES list as an explicit NULL, which
# Postgres rejects for a generated column). SQLite: a plain nullable text column,
# via _skip_computed_on_sqlite above -- unused by any SQLite-backed test, same as
# _embedding above.
_search_vector = TSVECTOR().with_variant(Text(), "sqlite")
_search_vector_computed = Computed("to_tsvector('english', content)", persisted=True)


class Chunk(Base):
    """BASELINE, reconcile with ingestion schema.

    Every column shape here (patient_id as a bare UUID, doc_type/access_scope
    as unconstrained text, source_document_id with no documents table) is a
    placeholder to unblock vector retrieval on synthetic data — none of it is
    ratified. See docs/FR-RAG-01_handoff.md.

    patient_id is nullable: NULL means an org-wide chunk (clinic policy,
    routing rules, guardrails, ...) visible in every patient's retrieval
    context, still gated by access_scope. See alembic 0022_chunks_org_wide.
    """

    __tablename__ = "chunks"

    id: Mapped[UUID] = mapped_column(_pg_uuid, primary_key=True, default=uuid4)
    patient_id: Mapped[UUID | None] = mapped_column(_pg_uuid, nullable=True, index=True)
    doc_type: Mapped[str] = mapped_column(Text, nullable=False)
    access_scope: Mapped[str] = mapped_column(Text, nullable=False)
    source_document_id: Mapped[UUID] = mapped_column(_pg_uuid, nullable=False)
    citation_tag: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    attachment_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(_embedding, nullable=False)
    search_vector: Mapped[str | None] = mapped_column(
        _search_vector, _search_vector_computed, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
