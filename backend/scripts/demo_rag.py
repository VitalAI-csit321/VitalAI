"""Interactive live demo: type one question at a time about Alice
(11111111-1111-1111-1111-111111111111), see answer / refusal_source /
decision / top_score printed immediately. Full-scope RetrievalContext (this
is a content-grounding demo, not a security-boundary demo).

Usage (run from backend/, against the docker-compose db + ollama, from the host):
    cd backend
    DATABASE_URL=postgresql+asyncpg://vitalai:vitalai@localhost:5432/vitalai \
    OLLAMA_BASE_URL=http://localhost:11434 \
    .venv/bin/python -m scripts.demo_rag

Type a question and press Enter. Empty line, "quit", or "exit" ends the demo.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from app.database import AsyncSessionLocal
from app.rag.answer import answer_question
from app.rag.retrieval import RetrievalContext

ALICE_ID = UUID("11111111-1111-1111-1111-111111111111")
FULL_CTX = RetrievalContext(
    patient_id=ALICE_ID,
    allowed_scopes=["general", "restricted", "sensitive"],
    role="clinician",
)


async def main() -> None:
    async with AsyncSessionLocal() as session:
        print("Ask about Alice. Empty line, 'quit', or 'exit' to stop.\n")
        while True:
            try:
                question = input("> ").strip()
            except EOFError:
                break
            if not question or question.lower() in {"quit", "exit"}:
                break
            result = await answer_question(session, question, FULL_CTX)
            print(f"answer:         {result.answer}")
            print(f"refusal_source: {result.refusal_source}")
            print(f"decision:       {result.gate_outcome.decision}")
            print(f"top_score:      {result.gate_outcome.top_score}\n")


if __name__ == "__main__":
    asyncio.run(main())
