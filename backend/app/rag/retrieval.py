"""Provenance-tagged chunk retrieval (FR-RAG-01), vector + Postgres full-text
hybrid by default.

BASELINE, reconcile with Matthew's ingestion schema: this module is built
against a baseline `chunks` table (see alembic/versions/0005_baseline_chunks.py
and app/models/chunk.py). The shapes of patient_id, doc_type, and access_scope
are placeholders invented to unblock retrieval on synthetic data — see
docs/FR-RAG-01_handoff.md for the reconciliation list. The public interface
below (RetrievalContext, RetrievedChunk, _security_filter, retrieve) is meant
to survive that reconciliation unchanged; only the underlying table/columns
should need to move.

Hybrid strategy (default, alembic 0023_chunks_hybrid_search): runs a vector
(cosine distance) query and a Postgres full-text (`search_vector @@
websearch_to_tsquery`) query independently, each still passed through
_security_filter, then fuses the two ranked candidate lists with Reciprocal
Rank Fusion. Fusion decides which chunks make the final top-k and their
order; RetrievedChunk.score/.distance always stay true cosine-similarity
values (never the RRF score) so app.rag.gating's calibrated
sufficiency_floor keeps the exact meaning it was calibrated against.
"""

from __future__ import annotations

import hashlib
import warnings
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.rag.embeddings import get_embedding_provider
from app.services.audit_service import record_event

EMBEDDING_DIM = 512
MIN_PGVECTOR_FOR_ITERATIVE_SCAN = (0, 8, 0)
# Standard Reciprocal Rank Fusion constant (Cormack et al. 2009); not tuned,
# doesn't need to be -- RRF only uses each list's rank position, not a
# calibrated weight, which is the point of picking it over a score blend.
RRF_K = 60
# Each ranker contributes more than the final k so fusion has real candidates
# to rerank across both signals, not just whatever one ranker's top-k already
# agreed on.
CANDIDATE_POOL_MULTIPLIER = 5
MIN_CANDIDATE_POOL = 50


@dataclass
class RetrievalContext:
    """Security/audit context for a retrieval call.

    BASELINE, reconcile with Matthew's ingestion schema: patient_id shape and
    the allowed_scopes vocabulary are placeholders.
    """

    # None scopes retrieval to org-wide chunks only (Chunk.patient_id == None
    # compiles to IS NULL in SQLAlchemy), used by non-patient-specific
    # queries like _generate_org_grounded_reply's clinic-hours/policy lookup.
    patient_id: UUID | None
    allowed_scopes: list[str]
    role: str
    actor: str = "system"


@dataclass
class RetrievedChunk:
    chunk_id: UUID
    patient_id: UUID | None
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

    Every retrieval path (vector, full-text) MUST filter through this
    function. Do not re-implement patient_id / access_scope filtering anywhere
    else a second copy is how a boundary check silently drifts out of sync.

    A NULL patient_id is an org-wide chunk (clinic policy, routing rules,
    guardrails, ...) and is visible from every patient context, still gated
    by access_scope like any other chunk.
    """
    return stmt.where(
        or_(Chunk.patient_id == ctx.patient_id, Chunk.patient_id.is_(None)),
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


async def _vector_candidates(
    session: AsyncSession,
    query_embedding: list[float],
    ctx: RetrievalContext,
    doc_type: str | None,
    limit: int,
) -> list[tuple[Chunk, float]]:
    """Chunks ranked by cosine distance, security-filtered. id is a tiebreaker
    for determinism only -- real embeddings essentially never tie exactly."""
    distance = Chunk.embedding.cosine_distance(query_embedding).label("distance")
    stmt = select(Chunk, distance)
    stmt = _security_filter(stmt, ctx)
    if doc_type is not None:
        stmt = stmt.where(Chunk.doc_type == doc_type)
    stmt = stmt.order_by(distance.asc(), Chunk.id.asc()).limit(limit)

    result = await session.execute(stmt)
    return [(row.Chunk, row.distance) for row in result.all()]


async def _fulltext_candidates(
    session: AsyncSession,
    query: str,
    ctx: RetrievalContext,
    doc_type: str | None,
    limit: int,
) -> list[Chunk]:
    """Chunks ranked by Postgres full-text rank, security-filtered. id
    tiebreaker is load-bearing here, unlike the vector side: short chunks
    collide on ts_rank often, and Postgres gives no order guarantee on ties
    without a deterministic secondary key."""
    tsquery = func.websearch_to_tsquery("english", query)
    rank = func.ts_rank(Chunk.search_vector, tsquery).label("rank")
    stmt = select(Chunk, rank).where(Chunk.search_vector.op("@@")(tsquery))
    stmt = _security_filter(stmt, ctx)
    if doc_type is not None:
        stmt = stmt.where(Chunk.doc_type == doc_type)
    stmt = stmt.order_by(rank.desc(), Chunk.id.asc()).limit(limit)

    result = await session.execute(stmt)
    return [row.Chunk for row in result.all()]


def _reciprocal_rank_fusion(*ranked_id_lists: list[UUID], k: int) -> list[UUID]:
    """Fuse ranked id lists into one top-k list. A chunk absent from a list
    contributes 0 from that list (standard RRF) -- this only sums over lists
    each id actually appears in, it never requires presence in every list, so
    a full-text-only or vector-only match is never dropped the way an
    inner-join merge of the two lists would drop it."""
    scores: dict[UUID, float] = {}
    for ranked_ids in ranked_id_lists:
        for rank, chunk_id in enumerate(ranked_ids):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)
    return sorted(scores, key=lambda cid: (-scores[cid], str(cid)))[:k]


async def _emit_gov_retrieve_event(
    session: AsyncSession,
    *,
    query: str,
    ctx: RetrievalContext,
    chunks: list[RetrievedChunk],
    k: int,
    strategy: str,
) -> None:
    """Append one retrieval.performed audit event per retrieve() call.

    Sink is app.models.audit.AuditEvent (append-only, DB-trigger enforced,
    see alembic/versions/0001_initial.py). If that table is ever removed
    before a replacement sink lands, this should become a no-op rather than
    raise, but today the sink exists, so this writes for real.
    query_hash, not raw query text, is recorded.
    """
    query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
    await record_event(
        session,
        actor=None,
        actor_label=ctx.actor,
        action="retrieval.performed",
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
    # This call has no accompanying business write it must stay atomic
    # with, commit here so the audit trail is durable even if the caller
    # never commits its own session.
    await session.commit()


async def retrieve(
    session: AsyncSession,
    query: str,
    ctx: RetrievalContext,
    k: int = 8,
    doc_type: str | None = None,
    strategy: str = "hybrid",
) -> list[RetrievedChunk]:
    """Embed `query` and return the top-k chunks visible to `ctx`.

    access_scope is always taken from `ctx.allowed_scopes`, never derived from
    `query` — the caller decides what a role/patient may see, not the search
    text.

    strategy="hybrid" (default): vector + Postgres full-text, fused with RRF.
    strategy="vector": the original single cosine-distance query, unchanged.
    """
    if strategy not in ("hybrid", "vector"):
        raise NotImplementedError(
            f"retrieval strategy {strategy!r} is not implemented "
            "(only 'hybrid' and 'vector' exist for FR-RAG-01)"
        )

    provider = get_embedding_provider()
    query_embedding = await provider.embed_query(query)
    if len(query_embedding) != EMBEDDING_DIM:
        raise ValueError(
            f"embedding provider returned a {len(query_embedding)}-dim vector, "
            f"expected {EMBEDDING_DIM} (query vs. ingestion embedder mismatch)"
        )

    await _configure_hnsw_session(session)

    if strategy == "vector":
        vector_rows = await _vector_candidates(session, query_embedding, ctx, doc_type, k)
        chunks = [
            RetrievedChunk(
                chunk_id=chunk.id,
                patient_id=chunk.patient_id,
                access_scope=chunk.access_scope,
                source_document_id=chunk.source_document_id,
                doc_type=chunk.doc_type,
                chunk_index=chunk.chunk_index,
                attachment_uri=chunk.attachment_uri,
                content=chunk.content,
                score=1.0 - distance,
                distance=distance,
            )
            for chunk, distance in vector_rows
        ]
    else:
        candidate_pool = max(k * CANDIDATE_POOL_MULTIPLIER, MIN_CANDIDATE_POOL)
        vector_rows = await _vector_candidates(
            session, query_embedding, ctx, doc_type, candidate_pool
        )
        fulltext_chunks = await _fulltext_candidates(session, query, ctx, doc_type, candidate_pool)

        chunk_by_id: dict[UUID, Chunk] = {}
        distance_by_id: dict[UUID, float] = {}
        for chunk, distance in vector_rows:
            chunk_by_id[chunk.id] = chunk
            distance_by_id[chunk.id] = distance
        vector_id_order = [chunk.id for chunk, _distance in vector_rows]

        for chunk in fulltext_chunks:
            chunk_by_id.setdefault(chunk.id, chunk)
        fulltext_id_order = [chunk.id for chunk in fulltext_chunks]

        fused_ids = _reciprocal_rank_fusion(vector_id_order, fulltext_id_order, k=k)

        # Full-text-only matches (rare -- an exact-term hit outside the vector
        # candidate pool) have no cosine distance yet. Every returned chunk's
        # .score/.distance must still be a real cosine value, never the RRF
        # score, so app.rag.gating's sufficiency_floor keeps meaning what it
        # was calibrated against. The ids here already passed _security_filter
        # once (they only came from vector_rows/fulltext_chunks above), so
        # this lookup-by-id doesn't need the filter reapplied.
        missing_ids = [cid for cid in fused_ids if cid not in distance_by_id]
        if missing_ids:
            distance = Chunk.embedding.cosine_distance(query_embedding).label("distance")
            stmt = select(Chunk.id, distance).where(Chunk.id.in_(missing_ids))
            result = await session.execute(stmt)
            for row in result.all():
                distance_by_id[row.id] = row.distance

        chunks = [
            RetrievedChunk(
                chunk_id=cid,
                patient_id=chunk_by_id[cid].patient_id,
                access_scope=chunk_by_id[cid].access_scope,
                source_document_id=chunk_by_id[cid].source_document_id,
                doc_type=chunk_by_id[cid].doc_type,
                chunk_index=chunk_by_id[cid].chunk_index,
                attachment_uri=chunk_by_id[cid].attachment_uri,
                content=chunk_by_id[cid].content,
                score=1.0 - distance_by_id[cid],
                distance=distance_by_id[cid],
            )
            for cid in fused_ids
        ]

    await _emit_gov_retrieve_event(
        session, query=query, ctx=ctx, chunks=chunks, k=k, strategy=strategy
    )

    return chunks
