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
    else:
        assert outcome.sufficient is True
        assert outcome.reason is None
        assert outcome.decision == "proceed"


@pytest.mark.parametrize(
    "question",
    [
        "What did the doctor recommend for the patient's cholesterol?",
        "Is the patient's blood pressure normal?",
        "Why was the patient referred to cardiology?",
    ],
)
async def test_natural_language_question_clears_sufficiency_floor(
    seeded_chunks: AsyncSession, question: str
) -> None:
    """Regression guard for the calibration bug where sufficiency_floor=0.50 sat
    inside the real positive-score range: naturally-phrased questions (not keyword
    soup) about content that genuinely exists for this patient must still clear
    the floor, or the gate silently returns the hardcoded refusal before the LLM
    is ever asked.
    """
    ctx = RetrievalContext(
        patient_id=PATIENT_ALICE,
        allowed_scopes=["general", "restricted", "sensitive"],
        role="clinician",
    )
    chunks = await retrieve(seeded_chunks, question, ctx, k=8)
    outcome = evaluate_retrieval(chunks)

    assert outcome.decision != "manual_handling", (
        f"{question!r} scored {outcome.top_score}, below sufficiency_floor="
        f"{settings.sufficiency_floor} - a genuine question was gate-refused "
        "before reaching the LLM"
    )


async def test_no_visible_chunks_is_insufficient(seeded_chunks: AsyncSession) -> None:
    ctx = RetrievalContext(patient_id=PATIENT_ALICE, allowed_scopes=[], role="front_desk")
    chunks = await retrieve(seeded_chunks, "annual physical exam blood pressure", ctx, k=8)
    outcome = evaluate_retrieval(chunks)

    assert chunks == []
    assert outcome.sufficient is False
    assert outcome.reason == "no_results"
    assert outcome.decision == "manual_handling"
