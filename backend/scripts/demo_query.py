"""Demo script: run two RAG queries for Elizabeth Thomas and print the four
fields that matter for the client demo: answer, refusal_source, decision,
top_score.

Query 1 asks for general-scope info (registration form) with a general-only
RetrievalContext -> answered normally.
Query 2 asks about clinical content (consultation) with that same
general-only RetrievalContext -> blocked by the security filter in
app.rag.retrieval._security_filter before it ever reaches the LLM, since
consultation notes are access_scope="restricted".

Usage (run from backend/, against the docker-compose db + ollama, from the host):
    cd backend
    DATABASE_URL=postgresql+asyncpg://vitalai:vitalai@localhost:5432/vitalai \
    OLLAMA_BASE_URL=http://localhost:11434 \
    python -m scripts.demo_query
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from app.database import AsyncSessionLocal
from app.rag.answer import answer_question
from app.rag.retrieval import RetrievalContext

ELIZABETH_THOMAS_ID = UUID("c5397397-c9b3-48cc-9413-09975f47bf14")

GENERAL_ONLY_CTX = RetrievalContext(
    patient_id=ELIZABETH_THOMAS_ID,
    allowed_scopes=["general"],
    role="admin_staff",
)

QUERIES = [
    (
        "Query 1: answerable with general access",
        "What is Elizabeth Thomas's phone number?",
        GENERAL_ONLY_CTX,
    ),
    (
        "Query 2: blocked by the security filter (consultation is restricted, "
        "this context only has general access)",
        "What was Elizabeth Thomas's chief complaint at her consultation?",
        GENERAL_ONLY_CTX,
    ),
]


async def main() -> None:
    async with AsyncSessionLocal() as session:
        for label, question, ctx in QUERIES:
            result = await answer_question(session, question, ctx)
            print(f"\n=== {label} ===")
            print(f"question:       {question}")
            print(f"answer:         {result.answer}")
            print(f"refusal_source: {result.refusal_source}")
            print(f"decision:       {result.gate_outcome.decision}")
            print(f"top_score:      {result.gate_outcome.top_score}")


if __name__ == "__main__":
    asyncio.run(main())
