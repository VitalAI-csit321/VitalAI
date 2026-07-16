"""FR-RAG-01 retrieval tests.

Run against a real Postgres+pgvector database via the `seeded_chunks` /
`pg_session` fixtures in conftest.py. SQLite cannot exercise cosine_distance,
HNSW, or the SET LOCAL GUCs this module depends on.

BASELINE, reconcile with Matthew's ingestion schema: the corpus these tests
run against (scripts/synthetic_corpus/) is synthetic, and the chunks table it
seeds is the placeholder schema from alembic/versions/0005_baseline_chunks.py.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent
from app.models.chunk import Chunk
from app.rag.retrieval import RetrievalContext, retrieve
from scripts.synthetic_corpus.manifest import (
    ALICE_BILLING_DOC,
    ALICE_LAB_PANEL_DOC,
    ALICE_MENTAL_HEALTH_DOC,
    BOB_LAB_PANEL_DOC,
    PATIENT_ALICE,
    PATIENT_BOB,
    PATIENT_DAVE,
)

pytestmark = pytest.mark.asyncio


async def _get_chunk(session: AsyncSession, source_document_id, chunk_index: int = 0) -> Chunk:
    result = await session.execute(
        select(Chunk).where(
            Chunk.source_document_id == source_document_id,
            Chunk.chunk_index == chunk_index,
        )
    )
    return result.scalar_one()


async def test_shape_returns_at_most_k_with_provenance(seeded_chunks: AsyncSession) -> None:
    ctx = RetrievalContext(
        patient_id=PATIENT_ALICE,
        allowed_scopes=["general", "restricted", "sensitive"],
        role="physician",
    )
    results = await retrieve(seeded_chunks, "annual physical exam blood pressure", ctx, k=3)

    assert 0 < len(results) <= 3
    for chunk in results:
        assert chunk.source_document_id is not None
        assert chunk.doc_type
        assert isinstance(chunk.chunk_index, int)


async def test_patient_boundary_excludes_other_patients(seeded_chunks: AsyncSession) -> None:
    ctx = RetrievalContext(
        patient_id=PATIENT_ALICE,
        allowed_scopes=["general", "restricted", "sensitive"],
        role="physician",
    )
    results = await retrieve(seeded_chunks, "diabetes glucose management metformin", ctx, k=20)

    chunk_ids = [chunk.chunk_id for chunk in results]
    rows = await seeded_chunks.execute(select(Chunk.patient_id).where(Chunk.id.in_(chunk_ids)))
    patient_ids = {row[0] for row in rows}

    assert patient_ids == {PATIENT_ALICE}
    # k=20 exceeds Alice's total chunk count with every scope allowed, so
    # nothing should be truncated — a real zero-Bob-chunks proof, not a
    # coincidence of a small k.
    assert len(results) == 7


async def test_scope_boundary_excludes_disallowed_scope(seeded_chunks: AsyncSession) -> None:
    ctx = RetrievalContext(patient_id=PATIENT_ALICE, allowed_scopes=["general"], role="front_desk")
    results = await retrieve(seeded_chunks, "lab result cholesterol lipid panel", ctx, k=20)

    chunk_ids = [chunk.chunk_id for chunk in results]
    rows = await seeded_chunks.execute(select(Chunk.access_scope).where(Chunk.id.in_(chunk_ids)))
    scopes = {row[0] for row in rows}

    assert scopes == {"general"}
    # Alice's restricted lab_result chunks are the closest semantic match to
    # this query, yet must be fully excluded — proves the exclusion isn't
    # incidental to weak relevance.
    assert len(results) == 4


async def test_divergence_filters_on_access_scope_not_doc_type(seeded_chunks: AsyncSession) -> None:
    mental_health_chunk = await _get_chunk(seeded_chunks, ALICE_MENTAL_HEALTH_DOC)
    billing_chunk = await _get_chunk(seeded_chunks, ALICE_BILLING_DOC)
    ctx = RetrievalContext(patient_id=PATIENT_ALICE, allowed_scopes=["general"], role="front_desk")

    # doc_type "clinical_note" looks ordinary, but access_scope="sensitive"
    # must still block it, even when queried with its own content.
    results = await retrieve(seeded_chunks, mental_health_chunk.content, ctx, k=20)
    assert mental_health_chunk.id not in {chunk.chunk_id for chunk in results}

    # doc_type "sensitive_summary" sounds locked down, but access_scope="general"
    # must still allow it through.
    results = await retrieve(seeded_chunks, billing_chunk.content, ctx, k=20)
    assert billing_chunk.id in {chunk.chunk_id for chunk in results}


async def test_over_filter_regression_small_patient_returns_all_chunks(
    seeded_chunks: AsyncSession,
) -> None:
    ctx = RetrievalContext(patient_id=PATIENT_DAVE, allowed_scopes=["general"], role="physician")
    results = await retrieve(seeded_chunks, "medication list allergy history", ctx, k=8)

    rows = await seeded_chunks.execute(select(Chunk.id).where(Chunk.patient_id == PATIENT_DAVE))
    dave_chunk_ids = {row[0] for row in rows}

    assert len(results) == 2
    assert {chunk.chunk_id for chunk in results} == dave_chunk_ids


async def test_score_descending_and_self_match_ranks_first(seeded_chunks: AsyncSession) -> None:
    target = await _get_chunk(seeded_chunks, ALICE_LAB_PANEL_DOC, chunk_index=0)
    ctx = RetrievalContext(
        patient_id=PATIENT_ALICE,
        allowed_scopes=["general", "restricted", "sensitive"],
        role="physician",
    )
    results = await retrieve(seeded_chunks, target.content, ctx, k=7)

    scores = [chunk.score for chunk in results]
    assert scores == sorted(scores, reverse=True)
    assert results[0].chunk_id == target.id
    # Query and document embeddings use different prefixes (search_query:
    # vs search_document:), so even an exact self-match never scores a
    # perfect 1.0. Still expect a strong match, well above the sufficiency
    # floor (0.50).
    assert results[0].score > 0.85


async def test_provider_dimension_mismatch_raises(
    seeded_chunks: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _WrongDimProvider:
        async def embed_query(self, text: str) -> list[float]:
            return [0.0] * 128

        async def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [[0.0] * 128 for _ in texts]

    monkeypatch.setattr("app.rag.retrieval.get_embedding_provider", lambda: _WrongDimProvider())
    ctx = RetrievalContext(patient_id=PATIENT_ALICE, allowed_scopes=["general"], role="physician")

    with pytest.raises(ValueError, match="512"):
        await retrieve(seeded_chunks, "irrelevant query text", ctx, k=1)


async def test_audit_emits_one_gov_retrieve_event_per_call(seeded_chunks: AsyncSession) -> None:
    count_stmt = (
        select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "GOV-RETRIEVE")
    )
    before_count = (await seeded_chunks.execute(count_stmt)).scalar_one()

    query = "annual physical exam"
    ctx = RetrievalContext(
        patient_id=PATIENT_ALICE, allowed_scopes=["general"], role="physician", actor="dr_house"
    )
    results = await retrieve(seeded_chunks, query, ctx, k=3)

    after_count = (await seeded_chunks.execute(count_stmt)).scalar_one()
    assert after_count == before_count + 1

    event = (
        await seeded_chunks.execute(
            select(AuditEvent)
            .where(AuditEvent.action == "GOV-RETRIEVE")
            .order_by(AuditEvent.timestamp.desc())
            .limit(1)
        )
    ).scalar_one()

    assert event.actor_label == "dr_house"
    assert event.details["role"] == "physician"
    assert event.details["patient_id"] == str(PATIENT_ALICE)
    assert event.details["k"] == 3
    assert event.details["strategy"] == "vector"
    assert event.details["chunk_ids"] == [str(chunk.chunk_id) for chunk in results]
    assert event.details["source_document_ids"] == [
        str(chunk.source_document_id) for chunk in results
    ]
    assert query not in str(event.details)  # raw query text must never be stored


async def test_end_to_end_ranked_retrieval_with_provenance(seeded_chunks: AsyncSession) -> None:
    target = await _get_chunk(seeded_chunks, BOB_LAB_PANEL_DOC, chunk_index=0)
    ctx = RetrievalContext(
        patient_id=PATIENT_BOB, allowed_scopes=["restricted", "general"], role="physician"
    )
    results = await retrieve(seeded_chunks, target.content, ctx, k=3, doc_type="lab_result")

    assert len(results) > 0
    assert results[0].chunk_id == target.id
    assert results[0].doc_type == "lab_result"
    assert results[0].source_document_id == target.source_document_id
    scores = [chunk.score for chunk in results]
    assert scores == sorted(scores, reverse=True)


async def test_hybrid_strategy_not_implemented(seeded_chunks: AsyncSession) -> None:
    ctx = RetrievalContext(patient_id=PATIENT_ALICE, allowed_scopes=["general"], role="physician")
    with pytest.raises(NotImplementedError):
        await retrieve(seeded_chunks, "anything", ctx, strategy="hybrid")
