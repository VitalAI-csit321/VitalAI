# FR-RAG-01 — Provenance-tagged vector retrieval: handoff

**Status: implemented and passing, on a BASELINE schema.** The prior session
of this doc reported Step 1 blocked because no `chunks` table, `patient_id`
concept, `doc_type`, or `access_scope` existed anywhere in the codebase. That
blocker still stands as a fact about the *real* schema — nothing here changes
what Matthew's ingestion pipeline will eventually own. What changed is the
decision: instead of waiting on schema ratification, this session built a
throwaway baseline schema, wired real vector retrieval against it, and
verified the whole path end to end on a synthetic corpus. Every baseline
choice is marked BASELINE and listed in **Reconcile With Matthew** below.

## What runs

- **Migration**: `alembic/versions/0005_baseline_chunks.py` creates `chunks`
  (id, patient_id, doc_type, access_scope, source_document_id, chunk_index,
  attachment_uri, content, embedding vector(512)) with an HNSW
  (vector_cosine_ops) index and a `(patient_id, access_scope)` btree index. No
  CHECK constraints — the doc_type/access_scope vocab is placeholder.
- **Retrieval**: `app/rag/retrieval.py` — `RetrievalContext`, `RetrievedChunk`,
  `_security_filter` (the one shared `patient_id == ... AND access_scope IN
  (...)` predicate; every path must call it), and `retrieve()`
  (vector-only; `strategy="hybrid"` raises `NotImplementedError`). Sets
  `hnsw.iterative_scan='strict_order'`, `max_scan_tuples=20000`,
  `ef_search=100` via `SET LOCAL` before each query (pgvector on the dev db is
  0.8.2, so the iterative-scan path is live — the prior session's "unverified
  pgvector version" blocker is resolved). Emits one `GOV-RETRIEVE`
  `AuditEvent` per call, keyed by `query_hash` (sha256), never raw query text.
- **Synthetic corpus**: `scripts/synthetic_corpus/` — 10 fabricated documents
  across 4 patients (Alice, Bob, Carol, Dave), 5 `doc_type` values, 3
  `access_scope` values, 15 chunks total. `scripts/seed_synthetic_chunks.py`
  embeds and loads it (delete-then-insert, idempotent).
- **Tests**: `tests/test_rag_retrieval.py`, 10 tests against a real
  Postgres+pgvector connection (`tests/conftest.py::pg_session` /
  `seeded_chunks` — SAVEPOINT-per-test, dev data untouched). All passing.

## A bug found and fixed along the way

`app/rag/embeddings.py::NomicEmbedProvider` was calling
`model.encode(text)` with no `truncate_dim`. `nomic-embed-text-v1` natively
outputs 768-dim vectors; this project's schema has committed to `vector(512)`
since commit `501a476`. Nothing had ever exercised this path end to end
(Docker was broken all last session), so the mismatch was latent. Fixed by
passing `truncate_dim=512` to `encode()`. This is a real defect fix, not a
schema placeholder — flagging it separately from the BASELINE list below so
it doesn't get lost in the reconciliation pass.

Also: `nomic-embed-text-v1`'s remote modeling code requires `einops`, which
was missing from `requirements.txt`. Added it.

## Reconcile with Matthew — every placeholder in this baseline

1. **`chunks` table itself** (`alembic/versions/0005_baseline_chunks.py`,
   `app/models/chunk.py`) — this is a new, standalone table, not a repurposing
   of the existing unused `vector_store` table. When Matthew's ingestion
   schema lands, decide whether `chunks` is replatformed onto his table or his
   table is renamed/merged into this one. Whichever way, `retrieve()`'s
   `select(Chunk, ...)` and `_security_filter()` are the only places that
   touch the table shape directly — a real migration should only need to
   change `app/models/chunk.py` and re-point those two spots.
2. **`patient_id` model** — a bare `UUID` column, not a foreign key. There is
   still no separate patient entity in this codebase (patients only exist as
   `intake_cases.patient_name`, free text). The synthetic corpus invents 4
   patient UUIDs (`scripts/synthetic_corpus/manifest.py`) with no backing row
   anywhere. Decide whether `patient_id` becomes `intake_cases.id`-derived or
   a genuine new patient entity (one patient can plausibly have multiple
   intake cases).
3. **`doc_type` vocabulary** — placeholder values used: `clinical_note`,
   `lab_result`, `referral_letter`, `billing_record`, `sensitive_summary`. No
   CHECK constraint. Not ratified.
4. **`access_scope` vocabulary** — placeholder values used: `general`,
   `restricted`, `sensitive`. No CHECK constraint. Not ratified. The synthetic
   corpus deliberately includes two chunks (`ALICE_MENTAL_HEALTH_DOC`,
   `ALICE_BILLING_DOC` in the manifest) where `doc_type` and `access_scope`
   disagree with what the name would suggest, specifically to prove
   `_security_filter` keys on `access_scope` and never on `doc_type`. Keep
   that property — whatever the real vocab ends up being, `doc_type` and
   `access_scope` must stay two independently governed axes, not one
   collapsed into the other.
5. **`source_document_id`** — a bare UUID, no `documents` table exists to
   reference. Once one does, add the FK.
6. **`RetrievalContext.role` and `.actor`** — free-text placeholders used only
   for the `GOV-RETRIEVE` audit event (`role`/`actor_label`), not for
   filtering. `role` is not `app.models.user.UserRole` (that's staff
   application-login roles; this is meant to be a clinical-access role like
   "physician" — deliberately not unified, since patient-data access roles
   and app-login roles are different concerns). Decide whether these should
   ever converge.

## What did NOT need to change and shouldn't, post-reconciliation

- The `RetrievalContext` / `RetrievedChunk` / `_security_filter` / `retrieve()`
  interface. Swapping the underlying table only requires updating
  `app/models/chunk.py` and the two call sites inside `retrieval.py` that
  reference `Chunk` directly.
- The embedding provider contract (512-dim, `get_embedding_provider()`,
  assert-length-fail-loud). Ingestion and retrieval already share the same
  factory, so they cannot silently diverge on dimension again.
- The audit event shape (`GOV-RETRIEVE`, `query_hash` not raw text).

## Test results

```
tests/test_rag_retrieval.py — 10 passed (real Postgres+pgvector, docker-compose db, migrated to 0005)
full suite (tests/) — 49 passed, 3 skipped, 1 xfailed, 0 failed
ruff check .   — clean
mypy app/rag/retrieval.py app/models/chunk.py app/rag/embeddings.py scripts/ — clean (0 issues)
mypy . (whole repo) — 4 pre-existing errors, all outside this change (verified identical on
                       the branch before this session's edits via `git stash`)
```

The 3 skipped are `tests/test_audit_trigger.py` (pre-existing; skips without
`POSTGRES_TEST_URL`, which this session did not set — unrelated to FR-RAG-01).
The 1 xfailed is a pre-existing known triage-routing negation bug, also
unrelated.

## Docker/pgvector note

Docker Desktop crashed once mid-session (same corruption class as the prior
session's report) and hung a live `docker compose exec` connection along with
a running pytest process. A hard kill (`pkill -9`) and relaunch recovered it
within ~2 minutes this time, and the `postgres_data` named volume preserved
all prior state (migration + seeded rows) across the restart. If this
recurs and doesn't recover within a few minutes, stop and flag it — per the
FR-RAG-01 instructions, do not fall back to SQLite for anything touching
`chunks`.

See also `docs/retrieval_contract.md` for the field-level contract Matthew's
corpus must satisfy.
