"""appointment calendar fields, overlap constraint, status remap

Revision ID: 0026_appointment_calendar_fields
Revises: 0025_task_delete_and_read
Create Date: 2026-08-26 00:00:00.000000
"""

import secrets
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0026_appointment_calendar_fields"
down_revision: str | None = "0025_task_delete_and_read"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    # Status remap first: the frontend's "pending" IS the RBAC report's
    # "suggested". RENAME VALUE is transactional and preserves existing rows.
    bind.exec_driver_sql("ALTER TYPE appointment_status RENAME VALUE 'suggested' TO 'pending'")
    # ADD VALUE cannot be used in the same transaction that added it (Postgres
    # raises UnsafeNewEnumValueUsageError) and this migration's pre-flight
    # query and EXCLUDE constraint WHERE clause both reference 'completed'
    # later in this same script. autocommit_block commits the ADD VALUE on
    # its own and reopens a transaction for the rest of the migration -- this
    # is alembic's documented pattern for ALTER TYPE ... ADD VALUE.
    with op.get_context().autocommit_block():
        bind.exec_driver_sql("ALTER TYPE appointment_status ADD VALUE IF NOT EXISTS 'completed'")

    appointment_type = sa.Enum(
        "new_patient", "follow_up", "procedure", "other", name="appointment_type"
    )
    appointment_type.create(bind, checkfirst=True)

    op.add_column(
        "appointments",
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="30"),
    )
    op.add_column(
        "appointments",
        sa.Column("appointment_type", appointment_type, nullable=False, server_default="other"),
    )
    op.add_column("appointments", sa.Column("location", sa.String(255), nullable=True))
    op.add_column("appointments", sa.Column("reason", sa.Text(), nullable=True))
    op.add_column("appointments", sa.Column("internal_notes", sa.Text(), nullable=True))
    op.add_column("appointments", sa.Column("reference_code", sa.String(16), nullable=True))
    op.add_column(
        "appointments",
        sa.Column("notify_patient", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "appointments",
        sa.Column("notify_provider", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("appointments", sa.Column("series_id", sa.Uuid(), nullable=True))

    # Backfill reference_code for existing rows before applying NOT NULL/UNIQUE.
    rows = bind.execute(sa.text("SELECT id FROM appointments WHERE reference_code IS NULL")).all()
    for (row_id,) in rows:
        bind.execute(
            sa.text("UPDATE appointments SET reference_code = :code WHERE id = :id"),
            {"code": f"APT-{secrets.token_hex(3).upper()}", "id": row_id},
        )
    op.alter_column("appointments", "reference_code", nullable=False)
    op.create_unique_constraint("unq_appointment_reference_code", "appointments", ["reference_code"])

    op.create_check_constraint(
        "ck_appointment_duration_positive", "appointments", "duration_minutes > 0"
    )

    # Pre-flight: two appointments 15 minutes apart are legal under the old
    # UNIQUE(doctor_id, time_slot) and violate the new exclusion constraint.
    # Fail loudly with the offending rows rather than opaquely mid-ALTER.
    conflicts = bind.execute(
        sa.text(
            """
            SELECT a.id, b.id, a.doctor_id, a.time_slot, b.time_slot
            FROM appointments a
            JOIN appointments b
              ON a.doctor_id = b.doctor_id
             AND a.id < b.id
             AND a.status IN ('confirmed', 'completed')
             AND b.status IN ('confirmed', 'completed')
             AND tsrange(
                   (a.time_slot AT TIME ZONE 'UTC'),
                   (a.time_slot AT TIME ZONE 'UTC')
                     + make_interval(mins => a.duration_minutes)
                 ) && tsrange(
                   (b.time_slot AT TIME ZONE 'UTC'),
                   (b.time_slot AT TIME ZONE 'UTC')
                     + make_interval(mins => b.duration_minutes)
                 )
            """
        )
    ).all()
    if conflicts:
        raise RuntimeError(
            "Cannot add excl_doctor_overlap: existing appointments already overlap. "
            f"Resolve these first: {conflicts}"
        )

    bind.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.drop_constraint("unq_doctor_timeslot", "appointments", type_="unique")
    # timestamptz + interval is STABLE, not IMMUTABLE, so it cannot appear in an
    # index expression. Normalising to a fixed zone first is immutable and works.
    bind.exec_driver_sql(
        """
        ALTER TABLE appointments ADD CONSTRAINT excl_doctor_overlap
          EXCLUDE USING gist (
            doctor_id WITH =,
            tsrange((time_slot AT TIME ZONE 'UTC'),
                    (time_slot AT TIME ZONE 'UTC')
                      + make_interval(mins => duration_minutes)) WITH &&
          ) WHERE (status IN ('confirmed', 'completed'))
        """
    )

    op.alter_column("appointments", "duration_minutes", server_default=None)
    op.alter_column("appointments", "appointment_type", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("ALTER TABLE appointments DROP CONSTRAINT excl_doctor_overlap")
    op.create_unique_constraint(
        "unq_doctor_timeslot", "appointments", ["doctor_id", "time_slot"]
    )
    op.drop_constraint("ck_appointment_duration_positive", "appointments", type_="check")
    op.drop_constraint("unq_appointment_reference_code", "appointments", type_="unique")
    for column in (
        "series_id",
        "notify_provider",
        "notify_patient",
        "reference_code",
        "internal_notes",
        "reason",
        "location",
        "appointment_type",
        "duration_minutes",
    ):
        op.drop_column("appointments", column)
    sa.Enum(name="appointment_type").drop(bind, checkfirst=True)
    bind.exec_driver_sql("ALTER TYPE appointment_status RENAME VALUE 'pending' TO 'suggested'")
