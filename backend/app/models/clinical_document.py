import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ClinicalDocType(enum.StrEnum):
    """Clinical doc types only. registration_form and appointment_history are
    general documents (scripts/ingest_corpus.py's DOC_TYPE_TO_SCOPE maps both
    to "general" scope), not clinical, so they don't belong in this
    UPLOAD_CLINICAL-gated upload's vocabulary. Confirmed with Amin 2026-07-24.
    """

    CONSULTATION = "consultation"
    PATHOLOGY_REPORT = "pathology_report"
    PRESCRIPTION = "prescription"


class ClinicalDocument(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Report section 8 steps 3-4: the stored file plus its extracted text.

    source_document_id on Chunk (app/models/chunk.py) is a soft reference to
    this table's id, not a DB-enforced FK - see the Phase 5 design doc for
    why (the offline synthetic-corpus chunks have no corresponding row here).
    """

    __tablename__ = "clinical_documents"

    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), nullable=False)
    doc_type: Mapped[ClinicalDocType] = mapped_column(
        Enum(
            ClinicalDocType,
            name="clinical_doc_type",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
