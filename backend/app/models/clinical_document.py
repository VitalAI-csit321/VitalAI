import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ClinicalDocType(enum.StrEnum):
    """Every document type a patient record can hold, clinical or not.

    Was clinical-only (consultation/pathology_report/prescription) on the
    reasoning that registration_form and appointment_history are general
    documents and don't belong in an UPLOAD_CLINICAL-gated vocabulary
    (Amin, 2026-07-24). Widened 2026-09-18 (Amin) so the whole synthetic
    corpus can be stored as real PDF documents behind a patient's record
    instead of as bare chunks -- see scripts/ingest_corpus_documents.py.
    Sensitivity is not this enum's job: access_scope comes from
    app.rag.doc_scopes, which still maps these to general/restricted/sensitive.
    """

    CONSULTATION = "consultation"
    CONSULTATION_NOTE = "consultation_note"
    PATHOLOGY_REPORT = "pathology_report"
    PRESCRIPTION = "prescription"
    REGISTRATION_FORM = "registration_form"
    APPOINTMENT_HISTORY = "appointment_history"
    REFERRAL_LETTER = "referral_letter"
    CARE_PLAN = "care_plan"
    SPECIALIST_LETTER = "specialist_letter"
    HOSPITAL_DISCHARGE_SUMMARY = "hospital_discharge_summary"
    EXTERNAL_IMAGING_REPORT = "external_imaging_report"
    CONSENT_RECORD = "consent_record"


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
