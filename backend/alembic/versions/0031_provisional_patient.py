"""provisional patients: nullable dob/gender, is_provisional, purged_at

A patient identified from an inbound message has a name and a contact address
and nothing else, which dob/gender NOT NULL made impossible to record. The
provisional marker is a column of its own rather than a PatientStatus value,
because patient_service.update_patient recomputes status from profile
completeness on every edit and would overwrite it.

purged_at supports anonymise-in-place for unclaimed provisional rows. A hard
DELETE is not an option: no FK referencing patients.id declares an ondelete,
so it would raise rather than cascade, and it would break the audit hash
chain.

downgrade() restores the NOT NULL constraints, which requires backfilling any
row that has no dob or gender -- exactly the provisional rows this migration
exists to allow. They are anonymised to a sentinel rather than deleted, for
the same referential reasons as above.

Revision ID: 0031_provisional_patient
Revises: 0030_widen_clinical_doc_type
Create Date: 2026-09-19 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0031_provisional_patient"
down_revision: str | None = "0030_widen_clinical_doc_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("patients", "dob", existing_type=sa.Date(), nullable=True)
    op.alter_column(
        "patients",
        "gender",
        existing_type=sa.Enum("male", "female", "non_binary", name="gender"),
        nullable=True,
    )
    op.add_column(
        "patients",
        sa.Column(
            "is_provisional",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("patients", sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_patients_is_provisional", "patients", ["is_provisional"])


def downgrade() -> None:
    op.drop_index("ix_patients_is_provisional", table_name="patients")
    op.drop_column("patients", "purged_at")
    op.drop_column("patients", "is_provisional")
    # NOT NULL cannot be restored while provisional rows hold NULLs. Sentinel
    # values keep the rows (and everything referencing them) intact; a
    # 1900-01-01 dob is visibly not real data.
    op.execute("UPDATE patients SET dob = DATE '1900-01-01' WHERE dob IS NULL")
    op.execute("UPDATE patients SET gender = 'non_binary' WHERE gender IS NULL")
    op.alter_column("patients", "dob", existing_type=sa.Date(), nullable=False)
    op.alter_column(
        "patients",
        "gender",
        existing_type=sa.Enum("male", "female", "non_binary", name="gender"),
        nullable=False,
    )
