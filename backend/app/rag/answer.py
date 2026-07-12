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
from app.rag.gating import RetrievalGateOutcome, evaluate_retrieval
from app.rag.retrieval import RetrievalContext, retrieve

NOT_ENOUGH_INFO_ANSWER = (
    "I don't have enough information in this patient's records to answer that."
)

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
    session: AsyncSession, question: str, ctx: RetrievalContext
) -> AnswerResult:
    chunks = await retrieve(session, question, ctx)
    gate_outcome = evaluate_retrieval(chunks)

    if gate_outcome.decision == "manual_handling":
        return AnswerResult(
            answer=NOT_ENOUGH_INFO_ANSWER,
            refusal_source="gate",
            gate_outcome=gate_outcome,
        )

    context_text = "\n\n".join(chunk.content for chunk in gate_outcome.chunks)
    prompt = _PROMPT_TEMPLATE.format(
        refusal_sentinel=NOT_ENOUGH_INFO_ANSWER, context=context_text, question=question
    )

    llm = get_llm()
    result = await llm.ainvoke(prompt)
    # Ollama returns str; Bedrock chat models return AIMessage with .content.
    answer_text = result if isinstance(result, str) else getattr(result, "content", str(result))

    if answer_text.strip() == NOT_ENOUGH_INFO_ANSWER.strip():
        return AnswerResult(
            answer=NOT_ENOUGH_INFO_ANSWER, refusal_source="llm", gate_outcome=gate_outcome
        )
    return AnswerResult(answer=answer_text, refusal_source="none", gate_outcome=gate_outcome)
