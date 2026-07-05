# FR-RAG-01 — Provenance-tagged vector retrieval: handoff

**Status: blocked at Step 1 (inspect-and-report). No retrieval code, migrations, or tests
were written.** This document reports what exists today, what's missing, and what a schema
owner needs to decide before Step 2 (build `backend/rag/retrieval.py`) can start.

## What was requested

FR-RAG-01 asked for vector-only, provenance-tagged retrieval keyed on `patient_id` and
`access_scope`, built against an existing `Chunk` model / `chunks` table with columns:
`patient_id, doc_type, access_scope, source_document_id, chunk_index, attachment_uri,
embedding (vector 512), content`.

## What was found (Step 1)

**Embedding provider — OK.** `app/rag/embeddings.py::get_embedding_provider()` returns
`NomicEmbedProvider` (sentence-transformers, dev) by default, or `BedrockTitanProvider`
(prod, currently `NotImplementedError`) when `LLM_PROVIDER=bedrock`. Both are declared for
512-dim vectors, matching `vector(512)`. There is exactly one factory; a query-path embedder
built against it would not diverge from ingestion's embedder.

**`Chunk` model / `chunks` table — does not exist.** A full-repo grep for `Chunk`,
`patient_id`, `access_scope`, `doc_type`, `source_document_id`, `chunk_index`,
`attachment_uri` returns nothing except two dead stubs:
- `app/rag/retriever.py::query_similar` — `raise NotImplementedError("...Phase 3")`
- `app/rag/service.py::retrieve_knowledge` — `raise NotImplementedError("...Phase 3")`

The only vector-bearing table is `vector_store`, created in
`alembic/versions/0003_vector_store.py`:

```
id, case_id (FK -> intake_cases, SET NULL), document_text, embedding vector(512),
metadata JSONB default '{}', created_at
```

Nothing in the codebase writes to `vector_store`; it is unused. It has no patient_id,
doc_type, access_scope, source_document_id, chunk_index, or attachment_uri — not as columns,
and nothing populates `metadata` either.

**No synthetic `patient_id` concept exists anywhere.** Patients are represented only as
`intake_cases.patient_name`, a free-text `String(255)`. There is no separate patient entity
and no stable synthetic ID for a patient independent of a case ID.

**`doc_type` vs `access_scope` CHECK comparison — moot.** Neither column exists in any
migration (`0001_initial.py`, `0002_triage_routed.py`, `0003_vector_store.py`,
`0004_human_review_tasks.py`), so there is no CHECK constraint on either to compare. This is
a larger finding than "the two sets are identical" — the distinction FR-RAG-01's divergence
test is designed to catch (access_scope vs. doc_type carrying different information) has
never been encoded in this schema at all.

**HNSW index — exists, but not on anything usable.**
`vector_store_embedding_hnsw_idx ... USING hnsw (embedding vector_cosine_ops)` exists on the
unused `vector_store` table only.

**pgvector version — not verified this session.** `docker-compose.yml` pins
`pgvector/pgvector:pg16`, a floating tag with no pinned pgvector version.
`docker-entrypoint-initdb.d/01_pgvector.sql` just runs `CREATE EXTENSION IF NOT EXISTS vector`.
Docker Desktop's local containerd store was corrupted this session (I/O errors reading image
blobs and its own metadata bolt db); a quit/relaunch did not clear it within ~10 minutes.
Per direction, no further (more invasive) Docker recovery was attempted — the user will
resolve Docker locally. **Action item: once Docker is healthy, run
`docker compose exec db psql -U vitalai -d vitalai -c "SELECT extversion FROM pg_extension WHERE extname='vector';"`
and record the result before Step 2 starts**, since the iterative_scan GUC (pgvector >=
0.8.0) determines part of the retrieval implementation.

**`pgvector` Python package — available transitively, not pinned directly.**
`requirements.txt` does not list `pgvector` itself, but it installs transitively via
`langchain-postgres>=0.0.6` (confirmed: `pgvector-0.3.6` in the resolved dependency set during
this session's `docker compose build`). If `langchain-postgres` is ever dropped, `pgvector`
would need to be pinned directly for the `Vector` SQLAlchemy type / `cosine_distance()`
comparator to keep working.

**Test infra — cannot exercise pgvector today.** `tests/conftest.py` defaults
`DATABASE_URL` to `sqlite+aiosqlite:///:memory:` when unset, and builds tables via
`Base.metadata.create_all`. SQLite has no HNSW, no `cosine_distance`, no `SET LOCAL`. Any
FR-RAG-01 test suite needs a real Postgres+pgvector connection; the sqlite default is not
sufficient even as a smoke test for this feature.

**No seed/sample document corpus exists (Step 5).** There is no `.txt` seed content, no
fixtures directory with document text, anywhere in the repo. The MRN/drug-name/billing-code
identifier-survival check from Step 5 could not be run — there is nothing to grep. This is
an absence finding, not a "clean" finding, and does not tell us anything about what
Matthew's ingestion generator will actually produce.

## Why Step 2 did not start

Building `backend/rag/retrieval.py` and its `Chunk` model as specified requires **inventing,
not filling a gap in, the following from scratch**:
1. A new `chunks` table (none exists — closest analog is the unused `vector_store`, which is
   shaped for something else entirely: `case_id` + `document_text` + free-form `metadata`).
2. A synthetic `patient_id` concept (patients currently have no identity separate from
   `intake_cases.patient_name`, a free-text field).
3. `doc_type` and `access_scope` columns and their CHECK vocabularies.
4. A `source_document_id` target (no `documents` table exists to reference).

The task's hard rule "do not invent schema" already anticipated a narrower version of this
(access_scope specifically missing a CHECK) and gave a documented fallback for that case.
It did not anticipate the entire table, the patient identity model, and both governance
columns being absent simultaneously. Given the instruction to stop and get the real schema
ratified before writing migrations, none of items 1–4 above were created.

## What was deliberately not built, and why

- `backend/rag/retrieval.py` (`RetrievalContext`, `RetrievedChunk`, `_security_filter`,
  `retrieve`) — depends on the chunks table existing; not started.
- Any Alembic migration for a `chunks` table — would require inventing schema (items 1–4
  above); explicitly deferred pending a schema decision.
- The pytest suite (10 cases from the brief) — no table to seed fixtures into.
- `docs/retrieval_contract.md` — deferred. Writing this now, before the schema is ratified,
  would effectively be dictating the schema unilaterally under the cover of documentation.
  Once patient_id / doc_type / access_scope / source_document_id are real, ratified columns,
  this doc should be written from that ratified shape, not the other way around.
- Ruff/mypy/pytest gates — nothing to run them against yet.

## Blockers

1. **No chunks table, patient_id concept, doc_type, or access_scope exist in this codebase.**
   (Severity: blocks all of Step 2 onward.) Needs a schema decision from whoever owns the
   ingestion/data model (referred to as "Matthew" in the FR-RAG-01 brief) before any
   migration is written. In particular: is `vector_store` meant to become this table, or is
   `chunks` a new, separate table? Is `patient_id` meant to be `intake_cases.id`, or a
   genuinely separate patient entity (since one patient could plausibly have multiple
   intake cases)?
2. **doc_type vs access_scope CHECK comparison is moot** because neither exists yet — flag
   for whoever designs the schema: these must be two independently governed vocabularies,
   not one collapsed into the other, per the hard rule that motivated FR-RAG-01's divergence
   test in the first place.
3. **pgvector version unverified.** Docker Desktop's containerd store was corrupted this
   session; recovery was left to the user rather than attempting a factory reset unilaterally
   (that would affect all local Docker state, not just this project). Verify before Step 2:
   the iterative_scan GUC used in the brief's `SET LOCAL` block requires pgvector >= 0.8.0.
4. **No seed/sample document corpus exists** to run the Step 5 identifier check against.
   A null finding here is only "nothing to grep," not "identifiers don't survive
   chunking" — it says nothing about Matthew's eventual generator output and does not close
   the hybrid-search identifier question for later.
5. **Test infra defaults to SQLite**, which cannot run any part of this feature. A real
   Postgres+pgvector test database (or a CI-only gate) will be needed regardless of how the
   schema question above is resolved.

## Recommended next step

Get a ratified answer to blocker 1 (schema owner sign-off on the chunks table shape,
patient identity model, and doc_type/access_scope vocabularies) before re-running Step 2.
Once that lands, `RetrievalContext`, `RetrievedChunk`, and `_security_filter` as specified in
the brief can be built directly against it — the interface design in the original brief
(single shared security filter, vector-only with a `NotImplementedError` seam for hybrid,
GOV-RETRIEVE audit hook) does not need to change regardless of how the schema question is
resolved.
