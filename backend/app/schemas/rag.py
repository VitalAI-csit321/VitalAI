from uuid import UUID

from pydantic import BaseModel, Field


class RagQueryRequest(BaseModel):
    patient_id: UUID
    question: str = Field(min_length=1)
