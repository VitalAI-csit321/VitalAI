"""patient profile fields

Revision ID: 0028_patient_profile_fields
Revises: 0027_app_settings
Create Date: 2026-09-18 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0028_patient_profile_fields"
down_revision: str | None = "0027_app_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STRING_COLUMNS = (
    "address", "indigenous_status", "preferred_language", "phone", "email",
    "emergency_contact_name", "emergency_contact_phone", "preferred_communication",
    "best_time_to_contact", "insurance_provider", "policy_number", "group_number",
    "medicare_number", "concession_card",
)
_TEXT_COLUMNS = ("known_conditions", "current_medications", "allergies")


def upgrade() -> None:
    for name in _STRING_COLUMNS:
        op.add_column("patients", sa.Column(name, sa.String(255), nullable=True))
    for name in _TEXT_COLUMNS:
        op.add_column("patients", sa.Column(name, sa.Text(), nullable=True))
    op.add_column("patients", sa.Column("insurance_expiry", sa.Date(), nullable=True))


def downgrade() -> None:
    for name in (*_STRING_COLUMNS, *_TEXT_COLUMNS, "insurance_expiry"):
        op.drop_column("patients", name)
