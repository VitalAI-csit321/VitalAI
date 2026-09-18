"""widen clinical_doc_type to the full corpus document vocabulary

The enum held three clinical types; the synthetic corpus emits twelve. Adding
the missing nine lets scripts/ingest_corpus_documents.py store every corpus
document as a real ClinicalDocument (PDF in object storage) instead of writing
bare chunks with no document row behind them, which is what left the Records
page showing "no documents" for patients the RAG answers about.

Postgres has no ALTER TYPE ... DROP VALUE, so downgrade() only reverts rows,
not the type: any document using a widened value moves back to 'consultation'.

Revision ID: 0030_widen_clinical_doc_type
Revises: 0029_consent_form_snapshot
Create Date: 2026-09-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0030_widen_clinical_doc_type"
down_revision: Union[str, None] = "0029_consent_form_snapshot"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_VALUES = (
    "consultation_note",
    "registration_form",
    "appointment_history",
    "referral_letter",
    "care_plan",
    "specialist_letter",
    "hospital_discharge_summary",
    "external_imaging_report",
    "consent_record",
)


def upgrade() -> None:
    for value in NEW_VALUES:
        # IF NOT EXISTS so a partially-applied run is re-runnable. Postgres 12+
        # allows ADD VALUE inside a transaction as long as the new value is not
        # used in that same transaction -- nothing here writes rows.
        op.execute(f"ALTER TYPE clinical_doc_type ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    values = ", ".join(f"'{v}'" for v in NEW_VALUES)
    op.execute(
        f"UPDATE clinical_documents SET doc_type = 'consultation' "
        f"WHERE doc_type::text IN ({values})"
    )
