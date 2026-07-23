from uuid import UUID

from pydantic import BaseModel, Field


class RagQueryRequest(BaseModel):
    """A grounded question against one patient's records.

    NOTE: `patient_id` is supplied by the caller because there is currently no
    link from an intake case to a patient — see PROVISIONAL note in
    app/routes/rag.py. `allowed_scopes` is deliberately NOT a field here: the
    access boundary is resolved server-side from the caller's role. A client
    that can name its own scopes has no boundary at all.
    """

    patient_id: UUID
    question: str = Field(min_length=1, max_length=2000)
    k: int = Field(default=8, ge=1, le=20)
    doc_type: str | None = None


class CitationOut(BaseModel):
    chunk_id: UUID
    source_document_id: UUID
    doc_type: str
    chunk_index: int
    citation_tag: str | None = None
    attachment_uri: str | None = None
    score: float
    content: str


class RagAnswerOut(BaseModel):
    answer: str
    # "none" = answered from context; "gate" = deterministic sufficiency/confidence
    # gate refused before any LLM call; "llm" = model declined from its context.
    refusal_source: str
    decision: str
    sufficient: bool
    reason: str | None
    confidence: float | None
    confidence_source: str | None
    top_score: float | None
    citations: list[CitationOut]
