"""Tests for app.rag.answer.answer_question().

Mocks retrieve() and get_llm(). No database, no real LLM call.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.rag.answer import NOT_ENOUGH_INFO_ANSWER, answer_question
from app.rag.retrieval import RetrievalContext, RetrievedChunk

pytestmark = pytest.mark.asyncio


def _chunk(score: float, content: str = "fabricated chunk content") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid4(),
        patient_id=uuid4(),
        access_scope="general",
        source_document_id=uuid4(),
        doc_type="note",
        chunk_index=0,
        attachment_uri=None,
        content=content,
        score=score,
        distance=1.0 - score,
    )


def _ctx() -> RetrievalContext:
    return RetrievalContext(patient_id=uuid4(), allowed_scopes=["general"], role="physician")


async def test_manual_handling_short_circuits_without_calling_llm() -> None:
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock()

    with (
        patch("app.rag.answer.retrieve", new=AsyncMock(return_value=[])),
        patch("app.rag.answer.get_llm", return_value=mock_llm),
    ):
        result = await answer_question(session=MagicMock(), question="any question", ctx=_ctx())

    assert result.answer == NOT_ENOUGH_INFO_ANSWER
    assert result.refusal_source == "gate"
    assert result.gate_outcome.decision == "manual_handling"
    mock_llm.ainvoke.assert_not_called()


async def test_sufficient_result_grounds_answer_in_retrieved_content() -> None:
    chunk = _chunk(score=0.90, content="Patient's prescription is amoxicillin 500mg.")
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value="Amoxicillin 500mg.")

    with (
        patch("app.rag.answer.retrieve", new=AsyncMock(return_value=[chunk])),
        patch("app.rag.answer.get_llm", return_value=mock_llm),
    ):
        result = await answer_question(
            session=MagicMock(), question="What is the prescription?", ctx=_ctx()
        )

    assert result.answer == "Amoxicillin 500mg."
    assert result.refusal_source == "none"
    assert result.gate_outcome.decision == "proceed"

    prompt = mock_llm.ainvoke.call_args.args[0]
    assert "Patient's prescription is amoxicillin 500mg." in prompt
    assert "What is the prescription?" in prompt


async def test_llm_refusal_sentinel_is_distinguished_from_gate_refusal() -> None:
    chunk = _chunk(score=0.90, content="Unrelated appointment note.")
    mock_llm = MagicMock()
    # Trailing whitespace, as a real model's raw output would include, proves
    # the strip() comparison catches it, not just an exact match.
    mock_llm.ainvoke = AsyncMock(return_value=f"{NOT_ENOUGH_INFO_ANSWER}\n ")

    with (
        patch("app.rag.answer.retrieve", new=AsyncMock(return_value=[chunk])),
        patch("app.rag.answer.get_llm", return_value=mock_llm),
    ):
        result = await answer_question(
            session=MagicMock(), question="What is the prescription?", ctx=_ctx()
        )

    assert result.answer == NOT_ENOUGH_INFO_ANSWER
    assert result.refusal_source == "llm"
    assert result.gate_outcome.decision == "proceed"
    mock_llm.ainvoke.assert_called_once()
