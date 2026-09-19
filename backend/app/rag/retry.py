"""Retrieval retry (build spec §7): one reformulated second attempt, graph only.

Both draft generators (email_service._generate_org_grounded_reply and
rag.answer.answer_question) retrieve through retrieve_gated. Without a
Reformulator it is exactly retrieve() + evaluate_retrieval(), so the flag-off
path makes no extra LLM call. One floor (settings.sufficiency_floor), two
attempts at most, no second decision surface.
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.language_models import BaseLanguageModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.guardrail import guarded_invoke
from app.models.user import User
from app.rag import retrieval
from app.rag.gating import RetrievalGateOutcome, evaluate_retrieval

_PROMPT = (
    "Rewrite the patient email below as a short search query for a medical clinic's "
    "own information documents (opening hours, fees, policies, services). Reply with "
    "the query only, nothing else.\n\n"
    "EMAIL: {query}\n\n"
    "QUERY:"
)


@dataclass
class Reformulator:
    """The second attempt's query rewrite, and the record of what the retry did.

    The record lives here because the draft generators return only
    (text, grounded); the graph's draft node reads it back into state.
    """

    session: AsyncSession
    actor: User
    llm: BaseLanguageModel
    attempts: int = 1
    # The rewrite that was actually retrieved with; None if there was none.
    query: str | None = None
    sufficient: bool | None = None

    async def rewrite(self, query: str) -> str:
        result = await guarded_invoke(
            self.session,
            self.llm,
            _PROMPT.format(query=query),
            actor=self.actor,
            route="email.reformulate",
        )
        text = result if isinstance(result, str) else getattr(result, "content", str(result))
        return text.strip()


def _normalise(text: str) -> str:
    return " ".join(text.casefold().split()).rstrip("?.!")


async def retrieve_gated(
    session: AsyncSession,
    query: str,
    ctx: retrieval.RetrievalContext,
    *,
    reformulate: Reformulator | None = None,
) -> RetrievalGateOutcome:
    """retrieve() then the sufficiency gate; with a Reformulator, one retry
    on a rewritten query when the first attempt misses the floor.

    An empty rewrite, or one that normalises to the original, skips the retry
    and counts as a failed second attempt.
    """
    outcome = evaluate_retrieval(await retrieval.retrieve(session, query, ctx))
    if reformulate is None:
        return outcome
    if not outcome.sufficient:
        reformulate.attempts = 2
        rewritten = await reformulate.rewrite(query)
        if rewritten and _normalise(rewritten) != _normalise(query):
            reformulate.query = rewritten
            outcome = evaluate_retrieval(await retrieval.retrieve(session, rewritten, ctx))
    reformulate.sufficient = outcome.sufficient
    return outcome
