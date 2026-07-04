"""add routed column to triage_results
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_triage_routed"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "triage_results",
        sa.Column(
            "routed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("triage_results", "routed")
