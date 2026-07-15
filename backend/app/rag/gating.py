"""Deterministic post-retrieval gates (FR-RAG-02 sufficiency, FR-RAG-03 confidence).

Both gates are pure functions of the scores already computed by
app.rag.retrieval.retrieve(), no LLM calls, no I/O. RAG-02 always runs first;
RAG-03 only runs when RAG-02 judged the retrieval sufficient.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.config import settings
from app.rag.retrieval import RetrievedChunk


class RetrievalGateOutcome(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    chunks: list[RetrievedChunk]
    sufficient: bool
    reason: str | None
    decision: str
    confidence: float | None
    confidence_source: str | None
    top_score: float | None


def _sufficiency_gate(chunks: list[RetrievedChunk]) -> tuple[bool, str | None, float | None]:
    if len(chunks) == 0:
        return False, "no_results", None

    top_score = max(c.score for c in chunks)
    if top_score < settings.sufficiency_floor:
        return False, "below_floor", top_score

    return True, None, top_score


def _confidence_gate(top_score: float) -> tuple[float, str, str]:
    confidence = top_score
    decision = "escalate" if confidence < settings.confidence_threshold else "proceed"
    return confidence, settings.confidence_source, decision


def evaluate_retrieval(chunks: list[RetrievedChunk]) -> RetrievalGateOutcome:
    sufficient, reason, top_score = _sufficiency_gate(chunks)

    if not sufficient:
        return RetrievalGateOutcome(
            chunks=chunks,
            sufficient=False,
            reason=reason,
            decision="manual_handling",
            confidence=None,
            confidence_source=None,
            top_score=top_score,
        )

    assert top_score is not None  # sufficient=True always sets top_score
    confidence, confidence_source, decision = _confidence_gate(top_score)
    return RetrievalGateOutcome(
        chunks=chunks,
        sufficient=True,
        reason=None,
        decision=decision,
        confidence=confidence,
        confidence_source=confidence_source,
        top_score=top_score,
    )
