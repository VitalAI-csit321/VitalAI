"""Grounded answer synthesis over the FR-RAG-02/03 gate outcome.

answer_question() runs retrieve() -> evaluate_retrieval() and only calls the
LLM when the gate decided there's enough to act on (decision != manual_handling).
On manual_handling it returns a fixed "not enough information" answer without
touching get_llm() at all. The LLM is never asked to guess from nothing.

The same sentinel string is also the LLM's instructed refusal output, so a
model that decides its context doesn't answer the question is indistinguishable
in wording from the gate's own refusal. refusal_source on AnswerResult tells the
two apart.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import get_llm
from app.llm.guardrail import guarded_invoke
from app.models.user import User
from app.rag.gating import RetrievalGateOutcome, evaluate_retrieval
from app.rag.retrieval import RetrievalContext, retrieve

NOT_ENOUGH_INFO_ANSWER = "I don't have enough information in this patient's records to answer that."

# Chunks scoring more than this below the top chunk are left out of the LLM
# context, not out of the retrieved set. 0.15 matches this corpus's documented
# score spread (see RAG_RETRIEVAL_TECHNICAL.md), so the margin adapts to the
# query instead of using a fixed absolute cutoff. Sufficiency and confidence are
# still computed on the full retrieved set in evaluate_retrieval(); this only
# trims what the model reads.
CONTEXT_SCORE_MARGIN = 0.15

_PROMPT_TEMPLATE = """You are a clinical assistant. Answer the QUESTION using ONLY \
the information in CONTEXT below. Do not use any outside knowledge. If CONTEXT does \
not contain the answer, respond with EXACTLY this sentence and nothing else: \
"{refusal_sentinel}"

CONTEXT:
{context}

QUESTION: {question}

ANSWER:"""


class AnswerResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    answer: str
    refusal_source: Literal["none", "gate", "llm"]
    gate_outcome: RetrievalGateOutcome


async def answer_question(
    session: AsyncSession, question: str, ctx: RetrievalContext, actor: User
) -> AnswerResult:
    chunks = await retrieve(session, question, ctx)
    gate_outcome = evaluate_retrieval(chunks)

    if gate_outcome.decision == "manual_handling":
        return AnswerResult(
            answer=NOT_ENOUGH_INFO_ANSWER,
            refusal_source="gate",
            gate_outcome=gate_outcome,
        )

    assert gate_outcome.top_score is not None  # sufficient=True always sets top_score
    context_chunks = [
        chunk
        for chunk in gate_outcome.chunks
        if chunk.score >= gate_outcome.top_score - CONTEXT_SCORE_MARGIN
    ]
    context_text = "\n\n".join(chunk.content for chunk in context_chunks)
    prompt = _PROMPT_TEMPLATE.format(
        refusal_sentinel=NOT_ENOUGH_INFO_ANSWER, context=context_text, question=question
    )

    llm = get_llm()
    result = await guarded_invoke(session, llm, prompt, actor=actor, route="/rag/query")
    # Ollama returns str; Bedrock chat models return AIMessage with .content.
    answer_text = result if isinstance(result, str) else getattr(result, "content", str(result))

    if answer_text.strip() == NOT_ENOUGH_INFO_ANSWER.strip():
        return AnswerResult(
            answer=NOT_ENOUGH_INFO_ANSWER, refusal_source="llm", gate_outcome=gate_outcome
        )
    return AnswerResult(answer=answer_text, refusal_source="none", gate_outcome=gate_outcome)
