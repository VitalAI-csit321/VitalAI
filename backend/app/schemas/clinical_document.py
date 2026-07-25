from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.enums import ClinicalDocType


class ClinicalDocumentOut(BaseModel):
    id: UUID
    patient_id: UUID
    doc_type: ClinicalDocType
    filename: str
    content_type: str
    size_bytes: int
    uploaded_by: UUID
    ingested_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class IngestResult(BaseModel):
    document_id: UUID
    chunk_count: int
    ingested_at: datetime
