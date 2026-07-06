from datetime import datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Integer, LargeBinary, Text, Uuid
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow

# postgresql.UUID with_variant Uuid() so SQLite (other suites' in-memory tests) still compiles
_pg_uuid = postgresql.UUID(as_uuid=True).with_variant(Uuid(), "sqlite")
# vector(512) has no SQLite equivalent; substitute an opaque blob so
# Base.metadata.create_all does not blow up for unrelated SQLite-backed test suites.
# Vector similarity queries against this column only run under the real Postgres
# fixture (see tests/conftest.py::pg_session).
_embedding = Vector(512).with_variant(LargeBinary(), "sqlite")


class Chunk(Base):
    """BASELINE, reconcile with Matthew's ingestion schema.

    Every column shape here (patient_id as a bare UUID, doc_type/access_scope
    as unconstrained text, source_document_id with no documents table) is a
    placeholder to unblock vector retrieval on synthetic data — none of it is
    ratified. See docs/FR-RAG-01_handoff.md.
    """

    __tablename__ = "chunks"

    id: Mapped[UUID] = mapped_column(_pg_uuid, primary_key=True, default=uuid4)
    patient_id: Mapped[UUID] = mapped_column(_pg_uuid, nullable=False, index=True)
    doc_type: Mapped[str] = mapped_column(Text, nullable=False)
    access_scope: Mapped[str] = mapped_column(Text, nullable=False)
    source_document_id: Mapped[UUID] = mapped_column(_pg_uuid, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    attachment_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(_embedding, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
