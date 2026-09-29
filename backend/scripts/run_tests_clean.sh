#!/usr/bin/env bash
#
# Run the backend suite against a throwaway database, then drop it.
#
# The shared dev database (`vitalai`) carries committed rows from every earlier
# run: app_settings, appointments, human_review_tasks, and an audit_events hash
# chain that is permanently broken. audit_events is append-only by design, so
# that chain can never be repaired in place. Those rows make roughly seventeen
# correct tests report failures that have nothing to do with the code under
# test. Reading them costs an evening; see backend/README.md.
#
# This is what CI does: virgin schema, alembic upgrade head, suite, drop. It
# never touches the shared dev database, which holds demo data other worktrees
# point at.
#
# Usage:
#   scripts/run_tests_clean.sh                     # whole suite
#   scripts/run_tests_clean.sh tests/test_audit_verify.py -x
#
set -euo pipefail

cd "$(dirname "$0")/.."

DB_NAME="vitalai_scratch_$$"
PG_USER=vitalai
PG_PASSWORD=vitalai
PG_HOST=127.0.0.1
PG_PORT=5432

# psql is not installed on the host; go through the compose `db` service (named
# `db`, not `postgres`). -T because there is no TTY in a script.
psql_postgres() {
    docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "$PG_USER" -d postgres "$@"
}

drop_scratch() {
    psql_postgres -c "DROP DATABASE IF EXISTS \"$DB_NAME\" WITH (FORCE);" >/dev/null
}
trap drop_scratch EXIT

echo "==> creating scratch database $DB_NAME"
drop_scratch
psql_postgres -c "CREATE DATABASE \"$DB_NAME\" OWNER $PG_USER;" >/dev/null

SCRATCH_URL="postgresql+asyncpg://${PG_USER}:${PG_PASSWORD}@${PG_HOST}:${PG_PORT}/${DB_NAME}"
export DATABASE_URL="$SCRATCH_URL"
# conftest.py's pg_session/seeded_chunks fixtures read RAG_TEST_DATABASE_URL and
# default to the shared dev database, and test_audit_hash_chain.py reads
# POSTGRES_TEST_URL. Without these two the Postgres-only tests would still run
# against `vitalai` and still read its leftover rows.
export RAG_TEST_DATABASE_URL="$SCRATCH_URL"
export POSTGRES_TEST_URL="$SCRATCH_URL"
export JWT_SECRET_KEY="${JWT_SECRET_KEY:-scratch-test-secret}"

echo "==> alembic upgrade head"
.venv/bin/alembic upgrade head

echo "==> pytest"
.venv/bin/python -m pytest "$@"
