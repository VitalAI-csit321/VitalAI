"""Integration test: retrieve() composed with evaluate_retrieval().

Complements test_rag_retrieval.py (retrieval alone) and test_rag_gating.py
(gating alone, on fabricated chunks) by locking in that the two compose
correctly against real embeddings/pgvector, the gap a manual demo script closed
by hand. Assertions re-derive the expected gate outcome from settings + the
real top_score rather than hardcoding embedding-model-dependent numbers, so
this doesn't get brittle if the embedding provider changes.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.rag.gating import evaluate_retrieval
from app.rag.retrieval import RetrievalContext, retrieve
from scripts.synthetic_corpus.manifest import PATIENT_ALICE

pytestmark = pytest.mark.asyncio


async def test_sufficient_query_gate_matches_settings(seeded_chunks: AsyncSession) -> None:
    ctx = RetrievalContext(
        patient_id=PATIENT_ALICE,
        allowed_scopes=["general", "restricted", "sensitive"],
        role="clinician",
    )
    chunks = await retrieve(seeded_chunks, "annual physical exam blood pressure", ctx, k=8)
    outcome = evaluate_retrieval(chunks)

    assert len(chunks) > 0
    assert outcome.chunks == chunks
    top_score = max(c.score for c in chunks)
    assert outcome.top_score == top_score

    if top_score < settings.sufficiency_floor:
        assert outcome.sufficient is False
        assert outcome.reason == "below_floor"
        assert outcome.decision == "manual_handling"
        assert outcome.confidence is None
        assert outcome.confidence_source is None
    else:
        assert outcome.sufficient is True
        assert outcome.reason is None
        assert outcome.confidence == top_score
        assert outcome.confidence_source == settings.confidence_source
        expected_decision = "proceed" if top_score >= settings.confidence_threshold else "escalate"
        assert outcome.decision == expected_decision


async def test_no_visible_chunks_is_insufficient(seeded_chunks: AsyncSession) -> None:
    ctx = RetrievalContext(patient_id=PATIENT_ALICE, allowed_scopes=[], role="front_desk")
    chunks = await retrieve(seeded_chunks, "annual physical exam blood pressure", ctx, k=8)
    outcome = evaluate_retrieval(chunks)

    assert chunks == []
    assert outcome.sufficient is False
    assert outcome.reason == "no_results"
    assert outcome.decision == "manual_handling"
    assert outcome.confidence is None
