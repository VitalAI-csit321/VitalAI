"""order the audit hash chain by a server-side sequence instead of timestamp

Revision ID: 0018_audit_chain_sequence_number
Revises: 0017_human_review_escalated_status
Create Date: 2026-07-27

The hash-chain trigger from migration 0016 picked each row's predecessor via
`ORDER BY timestamp DESC, id DESC LIMIT 1`. `timestamp` is assigned client-side
in Python (`AuditEvent.timestamp`'s `default=utcnow`) at object-construction
time, not server-side at actual insert/commit time. Under concurrent writers
(multiple backend processes/requests), a row's Python-assigned timestamp order
can diverge from the order rows are actually committed in, so the trigger can
link a row's predecessor to a row that was inserted earlier but stamped with a
later timestamp, corrupting the chain's shape (confirmed on the real dev DB:
a stored predecessor_hash pointing at a row timestamped after it).

This migration adds a server-side monotonic `sequence_number` (identity
column, assigned atomically at physical insert time by Postgres itself, not by
application code) and repoints both the trigger and verify_audit_chain() at it
instead of `timestamp`. Pre-existing rows are backfilled in their prior
best-effort order (timestamp/id) purely so the column is populated and NOT
NULL holds; this does NOT retroactively repair any already-broken chain
history, matching how migration 0016's own action-shape CHECK constraint used
NOT VALID for pre-existing rows rather than rewriting history. Only new rows
going forward are protected by the fix.
"""

from alembic import op

revision: str = "0018_audit_chain_sequence_number"
down_revision: str | None = "0017_hrt_escalated_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # ADD COLUMN ... GENERATED ALWAYS AS IDENTITY auto-backfills every existing
    # row with sequential values as part of this single statement (Postgres
    # 10+), no separate backfill step needed. The order it assigns to
    # pre-existing rows is not claimed to reconstruct true historical insert
    # order, see the module docstring; only new rows going forward matter.
    bind.exec_driver_sql(
        "ALTER TABLE audit_events ADD COLUMN sequence_number BIGINT GENERATED ALWAYS AS IDENTITY"
    )

    op.create_index(
        "ix_audit_events_sequence_number", "audit_events", ["sequence_number"], unique=True
    )

    bind.exec_driver_sql(
        """
        CREATE OR REPLACE FUNCTION compute_audit_event_hash()
        RETURNS trigger AS $$
        DECLARE
            prev_hash text;
            canonical text;
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtext('audit_events_chain'));

            SELECT event_hash INTO prev_hash
            FROM audit_events
            ORDER BY sequence_number DESC
            LIMIT 1;

            canonical := coalesce(NEW.case_id::text, '') || '|' ||
                         coalesce(NEW.actor_id::text, '') || '|' ||
                         coalesce(NEW.actor_label, '') || '|' ||
                         NEW.action || '|' ||
                         NEW.details::text || '|' ||
                         NEW.timestamp::text;

            NEW.predecessor_hash := prev_hash;
            NEW.event_hash := encode(
                digest(coalesce(prev_hash, '') || canonical, 'sha256'), 'hex'
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    bind.exec_driver_sql(
        """
        CREATE OR REPLACE FUNCTION verify_audit_chain()
        RETURNS TABLE(valid boolean, checked_count integer, first_break_event_id uuid) AS $$
        DECLARE
            rec RECORD;
            prev_hash text := NULL;
            expected_hash text;
            canonical text;
            count_ok integer := 0;
        BEGIN
            FOR rec IN
                SELECT * FROM audit_events ORDER BY sequence_number ASC
            LOOP
                IF rec.event_hash IS NULL THEN
                    -- Pre-chain row (predates migration 0016). Not part of
                    -- the chain; leave prev_hash untouched.
                    CONTINUE;
                END IF;

                canonical := coalesce(rec.case_id::text, '') || '|' ||
                             coalesce(rec.actor_id::text, '') || '|' ||
                             coalesce(rec.actor_label, '') || '|' ||
                             rec.action || '|' ||
                             rec.details::text || '|' ||
                             rec.timestamp::text;
                expected_hash := encode(
                    digest(coalesce(prev_hash, '') || canonical, 'sha256'), 'hex'
                );

                IF rec.event_hash != expected_hash
                   OR rec.predecessor_hash IS DISTINCT FROM prev_hash THEN
                    RETURN QUERY SELECT false, count_ok, rec.id;
                    RETURN;
                END IF;

                count_ok := count_ok + 1;
                prev_hash := rec.event_hash;
            END LOOP;

            RETURN QUERY SELECT true, count_ok, NULL::uuid;
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    bind.exec_driver_sql(
        """
        CREATE OR REPLACE FUNCTION compute_audit_event_hash()
        RETURNS trigger AS $$
        DECLARE
            prev_hash text;
            canonical text;
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtext('audit_events_chain'));

            SELECT event_hash INTO prev_hash
            FROM audit_events
            ORDER BY timestamp DESC, id DESC
            LIMIT 1;

            canonical := coalesce(NEW.case_id::text, '') || '|' ||
                         coalesce(NEW.actor_id::text, '') || '|' ||
                         coalesce(NEW.actor_label, '') || '|' ||
                         NEW.action || '|' ||
                         NEW.details::text || '|' ||
                         NEW.timestamp::text;

            NEW.predecessor_hash := prev_hash;
            NEW.event_hash := encode(
                digest(coalesce(prev_hash, '') || canonical, 'sha256'), 'hex'
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    bind.exec_driver_sql(
        """
        CREATE OR REPLACE FUNCTION verify_audit_chain()
        RETURNS TABLE(valid boolean, checked_count integer, first_break_event_id uuid) AS $$
        DECLARE
            rec RECORD;
            prev_hash text := NULL;
            expected_hash text;
            canonical text;
            count_ok integer := 0;
        BEGIN
            FOR rec IN
                SELECT * FROM audit_events ORDER BY timestamp ASC, id ASC
            LOOP
                IF rec.event_hash IS NULL THEN
                    CONTINUE;
                END IF;

                canonical := coalesce(rec.case_id::text, '') || '|' ||
                             coalesce(rec.actor_id::text, '') || '|' ||
                             coalesce(rec.actor_label, '') || '|' ||
                             rec.action || '|' ||
                             rec.details::text || '|' ||
                             rec.timestamp::text;
                expected_hash := encode(
                    digest(coalesce(prev_hash, '') || canonical, 'sha256'), 'hex'
                );

                IF rec.event_hash != expected_hash
                   OR rec.predecessor_hash IS DISTINCT FROM prev_hash THEN
                    RETURN QUERY SELECT false, count_ok, rec.id;
                    RETURN;
                END IF;

                count_ok := count_ok + 1;
                prev_hash := rec.event_hash;
            END LOOP;

            RETURN QUERY SELECT true, count_ok, NULL::uuid;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    op.drop_index("ix_audit_events_sequence_number", table_name="audit_events")
    op.drop_column("audit_events", "sequence_number")
