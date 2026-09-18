"""consent form snapshot

Revision ID: 0029_consent_form_snapshot
Revises: 0028_patient_profile_fields
Create Date: 2026-09-18 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0029_consent_form_snapshot"
down_revision: str | None = "0028_patient_profile_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("consent_records", sa.Column("form_snapshot", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("consent_records", "form_snapshot")
