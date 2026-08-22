"""Deterministic post-retrieval gate (FR-RAG-02 sufficiency).

A pure function of the scores already computed by app.rag.retrieval.retrieve(),
no LLM calls, no I/O.
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
    top_score: float | None


def _sufficiency_gate(chunks: list[RetrievedChunk]) -> tuple[bool, str | None, float | None]:
    if len(chunks) == 0:
        return False, "no_results", None

    top_score = max(c.score for c in chunks)
    if top_score < settings.sufficiency_floor:
        return False, "below_floor", top_score

    return True, None, top_score


def evaluate_retrieval(chunks: list[RetrievedChunk]) -> RetrievalGateOutcome:
    sufficient, reason, top_score = _sufficiency_gate(chunks)

    if not sufficient:
        return RetrievalGateOutcome(
            chunks=chunks,
            sufficient=False,
            reason=reason,
            decision="manual_handling",
            top_score=top_score,
        )

    return RetrievalGateOutcome(
        chunks=chunks,
        sufficient=True,
        reason=None,
        decision="proceed",
        top_score=top_score,
    )
