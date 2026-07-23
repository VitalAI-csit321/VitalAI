"""Vector-only, provenance-tagged chunk retrieval (FR-RAG-01).

BASELINE, reconcile with Matthew's ingestion schema: this module is built
against a baseline `chunks` table (see alembic/versions/0005_baseline_chunks.py
and app/models/chunk.py). The shapes of patient_id, doc_type, and access_scope
are placeholders invented to unblock retrieval on synthetic data — see
docs/FR-RAG-01_handoff.md for the reconciliation list. The public interface
below (RetrievalContext, RetrievedChunk, _security_filter, retrieve) is meant
to survive that reconciliation unchanged; only the underlying table/columns
should need to move.
"""

from __future__ import annotations

import hashlib
import warnings
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import Select, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent
from app.models.chunk import Chunk
from app.rag.embeddings import get_embedding_provider

EMBEDDING_DIM = 512
MIN_PGVECTOR_FOR_ITERATIVE_SCAN = (0, 8, 0)


@dataclass
class RetrievalContext:
    """Security/audit context for a retrieval call.

    BASELINE, reconcile with Matthew's ingestion schema: patient_id shape and
    the allowed_scopes vocabulary are placeholders.
    """

    patient_id: UUID
    allowed_scopes: list[str]
    role: str
    actor: str = "system"


@dataclass
class RetrievedChunk:
    chunk_id: UUID
    patient_id: UUID
    access_scope: str
    source_document_id: UUID
    doc_type: str
    chunk_index: int
    attachment_uri: str | None
    content: str
    score: float
    distance: float


def _security_filter(stmt: Select[Any], ctx: RetrievalContext) -> Select[Any]:
    """The one shared patient-data boundary check.

    Every retrieval path (vector today, hybrid later) MUST filter through this
    function. Do not re-implement patient_id / access_scope filtering anywhere
    else — a second copy is how a boundary check silently drifts out of sync.
    """
    return stmt.where(
        Chunk.patient_id == ctx.patient_id,
        Chunk.access_scope.in_(ctx.allowed_scopes),
    )


async def _configure_hnsw_session(session: AsyncSession) -> None:
    """Tune the HNSW index GUCs for this transaction only (SET LOCAL)."""
    version_str = await session.scalar(
        text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    )
    if version_str is None:
        raise RuntimeError("pgvector extension is not installed on this database")

    version = tuple(int(part) for part in version_str.split("."))[:3]
    if version >= MIN_PGVECTOR_FOR_ITERATIVE_SCAN:
        await session.execute(text("SET LOCAL hnsw.iterative_scan = 'strict_order'"))
        await session.execute(text("SET LOCAL hnsw.max_scan_tuples = 20000"))
        await session.execute(text("SET LOCAL hnsw.ef_search = 100"))
    else:
        # pgvector < 0.8.0 has no iterative_scan GUC. Compensate with a higher
        # ef_search so recall doesn't silently degrade; flagged per FR-RAG-01 brief.
        warnings.warn(
            f"pgvector {version_str} < 0.8.0: hnsw.iterative_scan unavailable, "
            "raising ef_search instead",
            stacklevel=2,
        )
        await session.execute(text("SET LOCAL hnsw.ef_search = 200"))


async def _emit_gov_retrieve_event(
    session: AsyncSession,
    *,
    query: str,
    ctx: RetrievalContext,
    chunks: list[RetrievedChunk],
    k: int,
    strategy: str,
) -> None:
    """Append one GOV-RETRIEVE audit event per retrieve() call.

    Sink is app.models.audit.AuditEvent (append-only, DB-trigger enforced —
    see alembic/versions/0001_initial.py). If that table is ever removed
    before a replacement sink lands, this should become a no-op rather than
    raise, but today the sink exists, so this writes for real.
    query_hash, not raw query text, is recorded.
    """
    query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
    event = AuditEvent(
        actor_label=ctx.actor,
        action="GOV-RETRIEVE",
        details={
            "role": ctx.role,
            "patient_id": str(ctx.patient_id),
            "query_hash": query_hash,
            "chunk_ids": [str(c.chunk_id) for c in chunks],
            "source_document_ids": [str(c.source_document_id) for c in chunks],
            "k": k,
            "top_score": chunks[0].score if chunks else None,
            "strategy": strategy,
        },
    )
    session.add(event)
    # Unlike app.services.audit_service.record_event, GOV-RETRIEVE has no
    # accompanying business write it must stay atomic with — commit here so
    # the audit trail is durable even if the caller never commits its own
    # session.
    await session.commit()


async def retrieve(
    session: AsyncSession,
    query: str,
    ctx: RetrievalContext,
    k: int = 8,
    doc_type: str | None = None,
    strategy: str = "vector",
) -> list[RetrievedChunk]:
    """Embed `query` and return the top-k chunks visible to `ctx`.

    access_scope is always taken from `ctx.allowed_scopes`, never derived from
    `query` — the caller decides what a role/patient may see, not the search
    text.
    """
    if strategy != "vector":
        raise NotImplementedError(
            f"retrieval strategy {strategy!r} is not implemented — vector only for FR-RAG-01"
        )

    provider = get_embedding_provider()
    query_embedding = await provider.embed(query)
    if len(query_embedding) != EMBEDDING_DIM:
        raise ValueError(
            f"embedding provider returned a {len(query_embedding)}-dim vector, "
            f"expected {EMBEDDING_DIM} (query vs. ingestion embedder mismatch)"
        )

    await _configure_hnsw_session(session)

    distance = Chunk.embedding.cosine_distance(query_embedding).label("distance")
    stmt = select(Chunk, distance)
    stmt = _security_filter(stmt, ctx)
    if doc_type is not None:
        stmt = stmt.where(Chunk.doc_type == doc_type)
    stmt = stmt.order_by(distance).limit(k)

    result = await session.execute(stmt)
    rows = result.all()

    chunks = [
        RetrievedChunk(
            chunk_id=row.Chunk.id,
            patient_id=row.Chunk.patient_id,
            access_scope=row.Chunk.access_scope,
            source_document_id=row.Chunk.source_document_id,
            doc_type=row.Chunk.doc_type,
            chunk_index=row.Chunk.chunk_index,
            attachment_uri=row.Chunk.attachment_uri,
            content=row.Chunk.content,
            score=1.0 - row.distance,
            distance=row.distance,
        )
        for row in rows
    ]

    await _emit_gov_retrieve_event(
        session, query=query, ctx=ctx, chunks=chunks, k=k, strategy=strategy
    )

    return chunks
