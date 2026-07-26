"""merge point: reconcile this branch's chain with task-call-models' tip

Revision ID: 0016_merge_call_routing
Revises: 0016_audit_hash_chain, 0018_call_routing_escalation
Create Date: 2026-07-27

Both parent branches' DDL is already physically present on the shared dev
DB (confirmed via information_schema before writing this). No-op: this
migration exists purely to give alembic a single head to continue from.
"""

revision: str = "0016_merge_call_routing"
down_revision: tuple[str, str] = ("0016_audit_hash_chain", "0018_call_routing_escalation")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
