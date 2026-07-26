"""audit hash chain and enrichment columns

Revision ID: 0016_audit_hash_chain
Revises: 0015_human_review_target_role
Create Date: 2026-07-26
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0016_audit_hash_chain"
down_revision: str | None = "0015_human_review_target_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # exec_driver_sql sends the string straight to the DBAPI driver with no
    # SQLAlchemy-side bind-parameter parsing. Every other raw-SQL call below
    # also uses it, on purpose: text()-based execution (what a plain
    # op.execute(str) uses internally) treats ":" followed by a word
    # character as a bind-parameter placeholder, which silently corrupts
    # both this migration's regex (":_") and the trigger bodies' "::text"/
    # "::uuid" casts below. Caught empirically: op.create_check_constraint's
    # first attempt rendered "(?:_[a-z]+)" as "(?NULL[a-z]+)" server-side.
    bind.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.add_column("audit_events", sa.Column("actor_role", sa.String(50), nullable=True))
    op.add_column("audit_events", sa.Column("risk_score", sa.Integer(), nullable=True))
    op.add_column("audit_events", sa.Column("outcome", sa.String(20), nullable=True))
    op.add_column("audit_events", sa.Column("ip_address", sa.String(45), nullable=True))
    op.add_column("audit_events", sa.Column("session_id", sa.String(64), nullable=True))
    op.add_column("audit_events", sa.Column("event_hash", sa.String(64), nullable=True))
    op.add_column("audit_events", sa.Column("predecessor_hash", sa.String(64), nullable=True))

    # NOT VALID: enforce the shape for every new row going forward without
    # retroactively validating existing history. Pre-existing rows include
    # GOV-RETRIEVE (uppercase-hyphenated, renamed to retrieval.performed in
    # a later change but not yet at the time this migration runs) and any
    # ad-hoc test.* actions from prior test runs against this database -
    # append-only history that predates this constraint, not something a
    # migration should ever try to rewrite.
    bind.exec_driver_sql(
        r"""
        ALTER TABLE audit_events
        ADD CONSTRAINT ck_audit_events_action_shape
        CHECK (action ~ '^[a-z]+(?:_[a-z]+)*(?:\.[a-z]+(?:_[a-z]+)*)+$') NOT VALID
        """
    )

    # Hash chain, computed server-side so it can't be skipped by a future
    # call site that forgets to call a helper (same reasoning as the
    # existing block_audit_modification trigger in 0001_initial.py).
    # A per-transaction advisory lock serializes the read-then-write
    # critical section (find the previous hash, then insert) so two
    # concurrent inserts can never both read the same "previous" row and
    # fork the chain. The lock releases automatically at transaction end.
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
        CREATE TRIGGER audit_events_compute_hash
        BEFORE INSERT ON audit_events
        FOR EACH ROW EXECUTE FUNCTION compute_audit_event_hash();
        """
    )

    # Verification walks the same canonical-string logic as the trigger
    # above, in the same SQL engine, so there is no risk of a Python-side
    # JSON/text canonicalization mismatch causing a false "tampered" result.
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
                    -- Pre-chain row (predates this migration). Not part of
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
    bind.exec_driver_sql("DROP FUNCTION IF EXISTS verify_audit_chain();")
    bind.exec_driver_sql("DROP TRIGGER IF EXISTS audit_events_compute_hash ON audit_events;")
    bind.exec_driver_sql("DROP FUNCTION IF EXISTS compute_audit_event_hash();")
    op.drop_constraint("ck_audit_events_action_shape", "audit_events", type_="check")
    op.drop_column("audit_events", "predecessor_hash")
    op.drop_column("audit_events", "event_hash")
    op.drop_column("audit_events", "session_id")
    op.drop_column("audit_events", "ip_address")
    op.drop_column("audit_events", "outcome")
    op.drop_column("audit_events", "risk_score")
    op.drop_column("audit_events", "actor_role")
