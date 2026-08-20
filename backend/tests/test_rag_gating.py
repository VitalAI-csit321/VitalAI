"""FR-RAG-02 / FR-RAG-03 gating tests.

Pure-function tests against fabricated RetrievedChunk objects with set scores
No database, no embedding provider, no LLM.
"""

from __future__ import annotations

from uuid import uuid4

from app.rag.gating import evaluate_retrieval
from app.rag.retrieval import RetrievedChunk


def _chunk(score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid4(),
        patient_id=uuid4(),
        access_scope="general",
        source_document_id=uuid4(),
        doc_type="note",
        chunk_index=0,
        attachment_uri=None,
        content="fabricated chunk content",
        score=score,
        distance=1.0 - score,
    )


def test_sufficient_proceeds() -> None:
    outcome = evaluate_retrieval([_chunk(0.80)])

    assert outcome.sufficient is True
    assert outcome.decision == "proceed"


def test_no_chunks_is_insufficient() -> None:
    outcome = evaluate_retrieval([])

    assert outcome.reason == "no_results"
    assert outcome.decision == "manual_handling"


def test_below_floor_is_insufficient() -> None:
    outcome = evaluate_retrieval([_chunk(0.30)])

    assert outcome.reason == "below_floor"
    assert outcome.decision == "manual_handling"
