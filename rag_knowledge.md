# RAG Retrieval Subsystem: Technical Reference

Authoritative technical context for the RAG retrieval, gating, and answer-synthesis
work (Amin's part of the sprint). Read this before touching anything under `app/rag/`,
the chunk model, the RAG migrations, or the RAG tests. If a change contradicts a
decision here, flag it rather than silently overriding.

Scope of this document: FR-RAG-01 (retrieval), FR-RAG-02 (sufficiency gate), FR-RAG-03
(confidence gate), and grounded answer synthesis. Everything downstream reads the
outputs defined here.

---

## 1. Pipeline shape

The chain is four stages, in order:

```
query + RetrievalContext
      -> retrieve()            (FR-RAG-01: security-filtered vector search)
      -> evaluate_retrieval()  (FR-RAG-02 sufficiency, then FR-RAG-03 confidence)
      -> answer_question()     (grounded synthesis, or refuse)
      -> AnswerResult
```

Each stage reads the previous stage's output. The gates are deterministic pure
functions of the retrieval scores. No LLM is involved in deciding sufficiency or
confidence. The LLM is only called to synthesize a final answer, and only when the
gates allow it.

Design rationale: sufficiency and confidence are treated as a system-level property (a
gate between retrieval and generation), not something the model self-assesses. Models
are unreliable at judging whether retrieved context is sufficient, so a deterministic
retrieval-score gate is more testable, reproducible, and defensible for a healthcare
governance system where the safe default is to abstain and route to a human. The LLM
autorater approach (Google Research, ~93% accuracy) is the documented post-MVP upgrade,
deliberately not built.

---

## 2. Data model: the `chunks` table

Columns (see app/models/chunk.py, alembic 0005_baseline_chunks + 0006_chunk_citation_tag):

| column             | type        | role |
|--------------------|-------------|------|
| id                 | UUID (PK)   | row identity, gen_random_uuid() |
| patient_id         | UUID        | security filter key |
| doc_type           | text        | document category, typed for DB-level filtering |
| access_scope       | text        | security boundary, typed |
| source_document_id | UUID        | stable machine key: joins, dedup, audit references |
| chunk_index        | integer     | chunk-level identity within a document |
| attachment_uri     | text (null) | pointer to scan/image; text report is embedded, image is not |
| content            | text        | the chunk text |
| embedding          | vector(512) | pgvector, cosine |
| created_at         | timestamptz | |
| citation_tag       | text (null) | readable citation: {patient_id_short}_{doc_type} |

Indexes: PK on id; HNSW on embedding (vector_cosine_ops), name
`chunks_embedding_hnsw_idx`; btree composite on (patient_id, access_scope), name
`chunks_patient_access_idx`.

### 2.1 The ID strategy (locked)

The single most important schema decision: **the machine key and the human citation
are separate columns, never one overloaded column.**

- `source_document_id` (UUID): opaque, stable, meaningless on purpose. Used for
  joins, dedup, delete, and the GOV-RETRIEVE audit event. A surrogate key must stay
  stable even if business attributes change, so it never encodes doc_type or patient.
- `citation_tag` (text): legible, for display: e.g. `a1b2c3d4_pathology`. Derived at
  ingest from the first 8 chars of the patient UUID plus the normalized doc_type.
- Chunk-level identity is `(source_document_id, chunk_index)`.

Why separate: a surrogate key and a readable citation are two different jobs. Trying to
make source_document_id do both (readable AND unique key) breaks audit/dedup the moment
a readable format lands on it. This is the standard production RAG pattern: a stable
document ID plus a separate source pointer. Do NOT put the readable string into
source_document_id.

**Not locked, and not addressed above: neither ID has a backing entity yet.**
`patient_id` and `source_document_id` are both bare UUIDs with nothing to reference:
no `Patient` table, no `documents` table. This was already flagged, before this file
existed, in `backend/docs/FR-RAG-01_handoff.md`'s "Reconcile with Matthew" list, and
independently rediscovered 2026-07-19 via a Figma-vs-backend gap analysis
(`docs/backend_gap_analysis.md`) that hit the same gap from the Patients-page side.
Two different angles landing on the same fact makes it a real one, not a one-off
nitpick. What's locked above is the *shape* (separate machine key vs. citation);
whether `patient_id` eventually becomes a real FK to a `patients` table, and
`source_document_id` an FK to a future `documents` table, is not decided here and
should not be assumed settled just because the column has existed since 0005.

Attribution is document-set level, not sentence level. LLMs synthesize across chunks,
so citation points to "these documents grounded this answer," not "this sentence came
from this line." Don't promise finer.

### 2.2 Typed security columns (locked)

`doc_type` and `access_scope` are typed TEXT columns, NOT JSONB. There is no CHECK
constraint on either column yet (see 0005_baseline_chunks.py). The access_scope
vocabulary is now ratified (see section 7), but adding the CHECK constraint is a
separate, later decision, not made yet. Keep them typed in the meantime; do not
switch to JSONB.

### 2.3 attachment_uri / scans

For a scan, embed the text report and store the image pointer in `attachment_uri`; the
image itself is not processed. No non-null attachment_uri exists in the current
baseline fixture, so that path is untested.

---

## 3. Embeddings (locked)

- **512 dimensions, everywhere.** Ingestion and query must use the same factory, same
  model, same 512 dims, or vectors don't match and every distance is meaningless.
- Dev: nomic-embed-text via Ollama. It silently emitted 768 dims, a real bug, fixed
  by truncating to 512.
- Prod: Titan Text Embeddings V2, which cannot produce 768, so 512 is the only viable
  cross-environment dimension.
- Distance: cosine. pgvector `<=>` operator, `vector_cosine_ops`, HNSW index.
- Query embedding goes through `get_embedding_provider()`, the same factory the seed
  script uses at ingest. retrieve() asserts len(query_embedding) == 512 and raises
  otherwise.
- **Asymmetric query/document prefixes.** NomicEmbedProvider prepends `search_query: `
  before encoding a query and `search_document: ` before encoding a document
  (EmbeddingProvider protocol: `embed_query` vs `embed_documents`). This is standard
  for retrieval-tuned models, not a bug. Consequence: even an exact self-match, the
  same text embedded once as a query and once as a document, never scores a perfect
  1.0 similarity. Expect a strong score, not a perfect one, when asserting on
  self-match behavior.

If distances ever look plausible but wrong, suspect (a) wrong operator (`<->` L2 or
`<#>` inner product instead of `<=>`), or (b) a dimension mismatch between ingest and
query. Both fail silently.

---

## 4. FR-RAG-01: retrieval (app/rag/retrieval.py)

`retrieve(session, query, ctx, k=8, doc_type=None, strategy="vector")` returns
`list[RetrievedChunk]`.

- `RetrievalContext` and `RetrievedChunk` both live in retrieval.py.
- Security filter (`_security_filter`) is a hard SQL `WHERE patient_id = ...
  AND access_scope IN (...)`, sourced entirely from RetrievalContext, **never** derived
  from the query text. This is the boundary; do not weaken it.
- `RetrievedChunk` fields: chunk_id, patient_id, access_scope, source_document_id,
  doc_type, chunk_index, attachment_uri, content, distance (raw cosine distance), and
  score (`1.0 - distance`, higher = closer).
- `score` is the number every downstream gate reads. distance is kept raw so gates can
  recompute if needed.
- Hybrid strategy raises NotImplementedError; only vector search is implemented.
- Emits a GOV-RETRIEVE audit event per call (Afra's audit consumes it; it references
  source_document_id, which is UUID and settled).

---

## 5. FR-RAG-02 / FR-RAG-03: the gates (app/rag/gating.py)

Two deterministic gates, run in order, both pure functions of the top score.

Config (pydantic Settings, app/config.py, configurable, not hardcoded):
- `SUFFICIENCY_FLOOR = 0.50`
- `CONFIDENCE_THRESHOLD = 0.75`
- `CONFIDENCE_SOURCE = "retrieval_similarity"`

FR-RAG-02 sufficiency (runs first):
- top_score = max(c.score) if chunks else None
- no chunks -> sufficient=False, reason="no_results", decision="manual_handling"
- top_score < floor -> sufficient=False, reason="below_floor", decision="manual_handling"
- else -> sufficient=True, reason=None, decision proceeds to confidence
- If not sufficient, confidence is NOT computed.

FR-RAG-03 confidence (only if sufficient):
- confidence = top_score, confidence_source = CONFIDENCE_SOURCE
- confidence < threshold -> decision="escalate"
- else -> decision="proceed"

Decisions and their meaning:
- `manual_handling`: withhold, route to human. Gate said insufficient.
- `escalate`: answer-and-flag. Sufficient but not confident; answer is produced AND
  flagged for review. NOT withheld.
- `proceed`: answer clean.

Outcome object carries: chunks, sufficient, reason, confidence, confidence_source,
top_score, decision. These are the fields the GOV-RETRIEVE audit event reads.

Floor calibration: done against the baseline corpus. On-topic query ~0.59, off-topic
~0.44, so 0.50 sits in the gap. The spread is narrow (~0.15), so the floor works but has
little margin; recalibrate on a richer corpus. Note: with a 0.75 confidence threshold
and best real scores ~0.59, most good queries currently `escalate` rather than
`proceed`, that is the threshold doing its job on a weak-signal corpus, not a bug.

Gates are pure functions of a number, so tests fabricate RetrievedChunk objects with
set scores and never hit the DB. Four cases: proceed (high), escalate (mid, ~0.60),
no_results (empty), below_floor (low).

---

## 6. Answer synthesis (app/rag/answer.py)

`answer_question(session, query, ctx)` -> `AnswerResult`.

Flow:
1. chunks = retrieve(...)
2. outcome = evaluate_retrieval(chunks)
3. if outcome.decision == "manual_handling": return refusal WITHOUT calling the LLM
   (refusal_source="gate"). The LLM is never invoked when the gate withholds; this is
   the anti-hallucination guarantee.
4. else: build a context-only prompt from the retrieved chunk content, call get_llm(),
   instruct it to answer strictly from context and emit the exact sentinel if the
   context is insufficient.
5. If the LLM returns the sentinel -> refusal_source="llm". Real answer ->
   refusal_source="none".

`AnswerResult` carries: answer, refusal_source in {"none","gate","llm"}, and
gate_outcome (so decision proceed/escalate stays visible to callers/audit).

### 6.1 Single refusal sentinel (locked)

One sentinel string, `NOT_ENOUGH_INFO_ANSWER`, is used in BOTH the gate short-circuit
and the LLM prompt instruction. The code compares the LLM output to the sentinel with
whitespace stripped (`result.strip() == SENTINEL.strip()`), because Ollama appends
trailing whitespace/newlines and a bare `==` misses the refusal. This was a real bug
that mislabeled LLM refusals as real answers (refusal_source="none" when it should be
"llm").

Why the three-way outcome matters: GOV-RETRIEVE needs to distinguish a real answer, a
gate refusal (retrieval found nothing sufficient), and an LLM refusal (context passed
the gate but the model still couldn't answer, including RAG over-refusal on noisy
context). A boolean "grounded" flag conflates the last two; refusal_source keeps them
separate. For a healthcare governance/audit trail this distinction is required.

### 6.2 get_llm() contract (locked)

get_llm() in app/llm/provider.py is the single abstraction point. Sync, zero-arg,
memoized. Generation is `await llm.ainvoke(prompt)`. Normalize output as
`result if isinstance(result, str) else getattr(result, "content", str(result))`.
Prod swap (Ollama -> Bedrock) is a config change, not a code refactor. Note: chat
models may return content as a list of blocks, fine for Ollama dev, revisit before the
Bedrock swap.

Live demo verified: "What is the patient LDL?" -> "LDL is 138 mg/dL" (grounded,
refusal_source none, decision escalate). Haemoglobin query -> honest refusal
(refusal_source llm) because the patient has a lipid panel, no haemoglobin. Same patient,
two correct behaviors: answer when grounded, refuse when the data isn't there.

---

## 7. access_scope vocabulary (ratified)

access_scope is keyed off doc_type, not folder label. Matthew's generator emits
exactly five doc_types, confirmed by listing the dataset on disk: consultation,
pathology_report, and prescription are clinical; registration_form and
appointment_history are admin. The mapping, defined as DOC_TYPE_TO_SCOPE in
scripts/ingest_corpus.py:

| doc_type | access_scope |
|---|---|
| consultation | restricted |
| pathology_report | restricted |
| prescription | restricted |
| registration_form | general |
| appointment_history | general |

Matthew's doc_type vocabulary above is canonical for access_scope purposes. The
sensitive tier stays defined in the vocabulary (general/restricted/sensitive), but no
doc_type currently maps to it, because the generator emits no sensitive document class
yet. An unknown or unmapped doc_type fails closed to restricted, never general, so an
unrecognised clinical document cannot leak to all staff.

Open dependency, owned by Matthew, not Amin: the generator needs to emit a sensitive
document class (mental health, sexual health, and similar) with a distinct filename
stem before anything can route to sensitive. Until then the sensitive tier has no
producer.

scripts/ingest_corpus.py imports from `backend/ingestion/matthew_corpus/`, a
directory that's now tracked in this repo (2026-07-19: moved in from an
untracked sibling folder via `git mv`; `Storage.py` and the stale `Embedder.py`
were deleted in the same pass, see below). Its transitive deps (ray, pypdf)
are declared in requirements.txt/requirements.lock as of the same date, so
both halves of the original ImportError-for-anyone-else problem are now fixed.

**2026-07-19: full corpus run, not just the demo.** ingest_corpus.py's
main() no longer hardcodes one patient; it loops every folder under Synth_Dataset,
each patient in its own delete-then-insert (one bad patient can't roll back the
rest). Ran for real against live Postgres: 100/100 patients landed after a retry
(first pass hit 98/100, the 2 misses were host disk pressure destabilizing Docker
mid-run, not a data or code bug, confirmed by retrying those 2 patients cleanly
once Docker was back up). `chunks` now holds 104 distinct patients / 515 rows
(100 Synth_Dataset + 4 from the original baseline seed corpus), embeddings
verified 512-dim across the board, access_scope breakdown correct.

**Embedder.py / Embedding_Provider.py, diffed against the canonical provider
above (2026-07-19):** neither is safe to use as-is against the real schema.
Both call `model.encode()` raw with no `truncate_dim=512` (native output is
768-dim) and neither implements the asymmetric query/document prefix this
file's docstring calls out as required, so routing ingestion through the
canonical embedder (as ingest_corpus.py already does) isn't just
preference, it's necessary. `Embedder.py` is a stale, pre-truncation-fix copy
of this file with nothing unique in it. `Embedding_Provider.py` does have a
real, working `boto3` Bedrock implementation this file's `BedrockTitanProvider`
lacks (it's still a `NotImplementedError` stub here), worth porting before
Phase 3 Bedrock work, not deleting unseen.

---

## 8. Testing rules

- **Real Postgres, not SQLite, for pgvector tests.** SQLite can't run pgvector. The
  Postgres test path builds schema by running `alembic upgrade head` (single source of
  truth), via `asyncio.to_thread` to avoid env.py's asyncio.run clashing with
  pytest-asyncio's loop. The SQLite path keeps create_all because migration 0001 is
  Postgres-only.
- Gate tests fabricate RetrievedChunk objects with set scores, no DB.
- Answer-synthesis tests mock retrieve() and get_llm(), no DB, no real LLM. Critical
  assertion: on manual_handling, ainvoke is NEVER called. Also assert a mocked LLM
  sentinel-with-whitespace maps to refusal_source="llm".
- The audit trigger (block_audit_modification) lives in migration 0001 and is the
  single source of truth. Tests must exercise the migration's trigger, never a
  hand-copied copy (a copy can pass while testing the wrong thing).
- Coverage: pyproject.toml sets `concurrency = ["greenlet"]` under [tool.coverage.run].
  Without it, async ORM code after the first flush/commit is misreported uncovered
  (this caused a false 51%; real services coverage ~100%).
- Embedding provider test doubles must implement `embed_query`/`embed_documents`, the
  actual EmbeddingProvider protocol methods, not `embed`/`embed_batch`. A stale mock
  with the wrong names fails with AttributeError instead of exercising the intended
  code path (e.g. a dimension-mismatch test never reaches the mismatch check).
- Don't assert a self-match score of exactly 1.0 (see section 3, asymmetric query/
  document prefixes). Assert a realistic high bound instead, e.g. `score > 0.85`.
- Never let a generic (non-RAG) test fixture tear down schema with something like
  DROP SCHEMA CASCADE or an unscoped drop_all. pg_session/seeded_chunks expect
  `chunks` (and any other RAG tables) to stay populated for the whole test session,
  not just for RAG-specific tests. A schema-nuking teardown anywhere in the suite
  silently empties those tables for every RAG test that runs after it. Per-test
  isolation for non-RAG tests must come from transaction rollback (see
  tests/conftest.py::db_session, client), never from dropping shared schema.

---

## 9. Environment quick reference

- DB from host: `DATABASE_URL="postgresql+asyncpg://vitalai:vitalai@localhost:5432/vitalai"`
  (.env uses Docker-internal `db`, unresolvable from host).
- Ollama from host: `OLLAMA_BASE_URL="http://localhost:11434"` (.env uses `ollama`).
- DB user is `vitalai`, model `gemma2:9b`.
- Reset DB clean: `docker compose down -v && docker compose up -d`.
- Full local check before push (run what CI runs):
  `ruff check app tests && ruff format --check app tests && DATABASE_URL=... JWT_SECRET_KEY=ci-test-secret python -m pytest tests/`
- **Containerized `api` service (docker-compose.yml), fixed 2026-07-19:** the `api`
  service loads the same `.env` that host-venv work points at `127.0.0.1` for
  `DATABASE_URL`. Inside a container `127.0.0.1` is the container itself, not the
  `db` container, so every DB query failed with `ConnectionRefusedError` (the
  server itself started fine and served `/health`, only real queries failed,
  looks like a healthy container until you hit an endpoint that touches the DB).
  Fixed with an explicit `environment: DATABASE_URL: ...@db:5432/...` override on
  the `api` service, which takes precedence over the `.env` value regardless of
  what host-mode has it set to. Verified live: full register → login → /me flow
  against the built container succeeds now.

---

## 10. Agent rules for this subsystem

- Do not push to remote. Do not invent migrations outside stated scope. Amin verifies
  agent work in his own terminal before accepting.
- Do not weaken the security filter (hard WHERE on patient_id + access_scope, never
  from query text).
- Do not overload source_document_id with the citation; citation_tag is its own column.
- Do not change the 512 embedding dimension.
- Do not call the LLM on a manual_handling decision.
- Keep the single refusal sentinel and the whitespace-tolerant comparison.
- Writing style for any generated text/comments: no em dashes, no overloaded adjectives
  (key, crucial, robust, etc.), active voice, plain and specific.