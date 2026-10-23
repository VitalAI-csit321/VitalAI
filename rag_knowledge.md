# Retrieval and Question Answering

This document describes how VitalAI answers a question from stored records: how
documents become searchable chunks, how retrieval enforces access control, how the
system decides whether it has enough evidence to answer, and how the final answer is
produced. The code lives in `backend/app/rag/`. The field-level contract for anything
that writes chunks is in `backend/docs/retrieval_contract.md`.

The pipeline covers three requirements: FR-RAG-01 (security-filtered retrieval),
FR-RAG-02 (the sufficiency gate) and grounded answer synthesis.

## 1. Pipeline

```
question + RetrievalContext
   -> retrieve()             app/rag/retrieval.py   security-filtered hybrid search
   -> evaluate_retrieval()   app/rag/gating.py      sufficiency gate
   -> answer_question()      app/rag/answer.py      grounded answer, or a refusal
   -> AnswerResult
```

`retrieve_gated()` in `app/rag/retry.py` wraps the first two steps. The gate is a
deterministic function of the retrieval scores. No LLM decides whether the evidence
is sufficient. The LLM is called only to write the answer, and only when the gate
allows it.

This is a deliberate choice. Language models are unreliable judges of whether their
context is enough, and a score threshold is reproducible and testable. For a
healthcare system the safe default is to say "not enough information" and leave the
question to a person.

All data is synthetic.

## 2. Where the data comes from

Every writer embeds through the same provider (`get_embedding_provider()`) and takes
`access_scope` from the same mapping (`app/rag/doc_scopes.py`).

| Source | Writer | patient_id | Notes |
|---|---|---|---|
| PDF uploaded through the app | `app/services/clinical_document_service.py` (`ingest_document`) | the patient | Text extracted by `app/rag/text_extraction.py`, split into 500-character chunks by `app/rag/chunking.py`. `source_document_id` is the `clinical_documents` row id. |
| Synthetic patient corpus as documents | `scripts/ingest_corpus_documents.py` | the patient | Renders each corpus file to PDF and sends it through the same upload and ingest service calls, so demo patients have real document rows. |
| Synthetic patient corpus as bare chunks | `scripts/ingest_corpus.py` | the patient | Reads `backend/ingestion/matthew_corpus/Synth_Dataset/`, one patient per transaction. Writes chunks with no `clinical_documents` row. `doc_type` comes from each patient's `manifest.json`, or the file name when there is none. |
| Clinic organisation profile | `scripts/ingest_org_profile.py` | NULL | Reads `Organization Profile Review/`. `doc_type` comes from a comment at the top of each file. |
| Test fixture corpus | `scripts/seed_synthetic_chunks.py` | fixed test patients | Data in `scripts/synthetic_corpus/manifest.py`, also used by the `seeded_chunks` test fixture. |

## 3. The `chunks` table

Defined in `app/models/chunk.py` and built by migrations `0005_baseline_chunks`,
`0006_chunk_citation_tag`, `0022_chunks_org_wide` and `0023_chunks_hybrid_search`.

| Column | Type | Role |
|---|---|---|
| id | UUID, primary key | Row identity |
| patient_id | UUID, nullable | Security filter key. NULL marks an org-wide chunk (0022). |
| doc_type | text | Document category. Optional retrieval filter, never used for security. |
| access_scope | text | Security tier: `general`, `restricted` or `sensitive` |
| source_document_id | UUID | Stable machine key for the parent document |
| citation_tag | text, nullable | Readable source label (0006) |
| chunk_index | integer | Position within the source document |
| attachment_uri | text, nullable | Link to the original file. Set by the upload path to the document's download route; NULL for corpus and org chunks. |
| content | text | The chunk text |
| embedding | vector(512) | pgvector embedding of `content` |
| search_vector | tsvector, generated | `to_tsvector('english', content)`, maintained by Postgres (0023). Writers never set it. |
| created_at | timestamptz | |

Indexes: `chunks_patient_access_idx` on (patient_id, access_scope),
`chunks_embedding_hnsw_idx` (HNSW, `vector_cosine_ops`) and `chunks_search_vector_idx`
(GIN on `search_vector`).

`doc_type` and `access_scope` are plain text columns with no CHECK constraint. They
are kept as typed columns, not JSONB, so the security filter is an ordinary indexed
SQL predicate.

### 3.1 Identifiers

The machine key and the human-readable citation are separate columns.

- `source_document_id` is an opaque UUID. It is used for joins, deduplication,
  deletion and the audit event. It never encodes the patient or document type, so it
  stays stable if those change.
- `citation_tag` is for display. It is the first 8 characters of the patient id plus
  the `doc_type` (for example `a1b2c3d4_pathology_report`), or `org_<doc_type>` for
  org-wide chunks.
- A single chunk is identified by `(source_document_id, chunk_index)`.

Neither identifier is a foreign key. A `patients` table exists, but
`chunks.patient_id` has no constraint to it and may be NULL. `source_document_id` is a
soft reference to `clinical_documents`: chunks from the upload path point at a real row,
while chunks written by `scripts/ingest_corpus.py` and `scripts/ingest_org_profile.py`
have no row there, so a foreign key would reject them.

Citations are at document level, not sentence level. The model writes across several
chunks, so a citation means "these chunks grounded this answer", not "this sentence
came from this line".

## 4. Embeddings

Embeddings are computed locally with sentence-transformers in `app/rag/embeddings.py`,
using `nomic-ai/nomic-embed-text-v1`. There is no hosted embedding provider. The
`EMBEDDING_PROVIDER` setting is only logged at startup; it does not select a provider.

- **512 dimensions everywhere.** The model's native output is 768 dimensions. The
  provider passes `truncate_dim=512` so every vector matches the `vector(512)` column.
  `retrieve()` raises `ValueError` if a query embedding is any other length. Ingestion
  and query must use the same provider, or distances are meaningless.
- **Cosine distance.** Queries use pgvector's `<=>` operator (through
  `cosine_distance()`), matching the `vector_cosine_ops` HNSW index.
- **Asymmetric prefixes.** `embed_query` prepends `search_query: ` and
  `embed_documents` prepends `search_document: `, as the model expects. As a result,
  the same text embedded once as a query and once as a document scores high but never
  exactly 1.0.
- `get_embedding_provider()` is cached, so the model loads once per process.

If scores look plausible but wrong, check for the wrong distance operator (`<->` or
`<#>`) or a dimension mismatch between ingest and query. Neither fails loudly.

## 5. Retrieval (FR-RAG-01)

`retrieve(session, query, ctx, k=8, doc_type=None, strategy="hybrid")` returns a list
of `RetrievedChunk`.

### 5.1 Security filter

`RetrievalContext` carries `patient_id`, `allowed_scopes`, `role` and `actor`. Every
query goes through `_security_filter`:

```
(patient_id = ctx.patient_id OR patient_id IS NULL)
AND access_scope IN ctx.allowed_scopes
```

The filter comes only from the context the caller builds, never from the query text.
It is the single place this boundary is written; both the vector and full-text queries
call it. Org-wide chunks (NULL `patient_id`) are visible from every patient context but
are still gated by `access_scope`. A context with `patient_id=None` sees only org-wide
chunks.

### 5.2 Hybrid search

The default strategy runs two ranked queries, each through the security filter:

1. Vector: chunks ordered by cosine distance to the query embedding.
2. Full text: chunks where `search_vector @@ websearch_to_tsquery('english', query)`,
   ordered by `ts_rank`.

Each returns a candidate pool of `max(k * 5, 50)`. The two lists are merged with
Reciprocal Rank Fusion (constant 60), which uses only rank positions, and the top `k`
are kept. A chunk found by only one of the two queries can still be returned.

Fusion decides which chunks are returned and in what order. It does not change the
score. `RetrievedChunk.score` is always cosine similarity (`1.0 - distance`), never the
fused value, so the sufficiency floor keeps the meaning it was calibrated against. A
chunk found only by full text has its cosine distance looked up by id; that id already
passed the security filter.

`strategy="vector"` runs the vector query alone. Any other value raises
`NotImplementedError`.

### 5.3 Audit

Each `retrieve()` call writes one `retrieval.performed` audit event and commits it. The
details hold the role, patient id, a SHA-256 hash of the query (not the query text), the
returned chunk ids and source document ids, `k`, the top score and the strategy.

## 6. Sufficiency gate (FR-RAG-02)

`evaluate_retrieval(chunks)` in `app/rag/gating.py` returns a `RetrievalGateOutcome`
with `chunks`, `sufficient`, `reason`, `decision` and `top_score`.

| Condition | sufficient | reason | decision |
|---|---|---|---|
| no chunks | False | `no_results` | `manual_handling` |
| top score below `sufficiency_floor` | False | `below_floor` | `manual_handling` |
| otherwise | True | None | `proceed` |

`manual_handling` means the system does not answer and the question is left to a
person. There is no other decision.

`sufficiency_floor` is `0.44` in `app/config.py`. The comment there records how it was
set: on real ingested chunks across five patients, off-domain queries topped out at
0.43 and genuine natural-language questions started at 0.4814. An earlier floor of
0.50 fell inside the genuine range and rejected valid questions, such as "tell me about
this patient" at 0.4933. The gap between the two groups is small, so the floor must be
recalibrated if the embedding model changes.

## 7. Answer synthesis

`answer_question(session, question, ctx, actor, feedback=None, reformulate=None)`
returns an `AnswerResult`.

1. `retrieve_gated()` runs retrieval and the gate.
2. If the decision is `manual_handling`, it returns the refusal sentence with
   `refusal_source="gate"` and never calls the LLM.
3. Otherwise it keeps, as context, the chunks scoring within `CONTEXT_SCORE_MARGIN`
   (0.15) of the top chunk. The gate has already run on the full retrieved set; this
   only limits what the model reads.
4. It builds a prompt that tells the model to answer only from the context and, if the
   context does not contain the answer, to reply with exactly the refusal sentence.
   `feedback` (a reviewer's reason for rejecting an earlier draft) is added to the
   prompt but never to the retrieval query.
5. It calls the model through `guarded_invoke()` (`app/llm/guardrail.py`). That checks
   the prompt against injection patterns first; on a match it writes a
   `governance.input_blocked` audit event and raises `InputBlockedError` without
   calling the model. `/rag/query` turns this into a 422.
6. If the reply is the refusal sentence, the result has `refusal_source="llm"`.
   Otherwise `refusal_source="none"` and `citations` holds the context chunks.

`AnswerResult` fields: `answer`, `refusal_source` (`none`, `gate` or `llm`),
`gate_outcome` (the full retrieved set and gate decision) and `citations` (only the
chunks the model read; empty on both refusal paths).

### 7.1 One refusal sentence

`NOT_ENOUGH_INFO_ANSWER` in `app/rag/answer.py` is used both as the gate's refusal and
as the exact text the model is told to return. The model's reply is compared with
whitespace stripped (`answer_text.strip() == NOT_ENOUGH_INFO_ANSWER.strip()`), because
models often add a trailing newline and a plain `==` would record a refusal as a real
answer.

The three-way `refusal_source` matters for the audit trail. It separates a real answer,
a refusal because retrieval found nothing good enough, and a refusal by the model when
the evidence passed the gate but did not answer the question. A single "grounded"
flag would merge the last two.

### 7.2 Retrieval retry

`retrieve_gated()` accepts an optional `Reformulator`. Without one it is exactly
`retrieve()` followed by `evaluate_retrieval()`. With one, if the first attempt fails
the gate, the LLM rewrites the query (through `guarded_invoke`) and retrieval runs once
more with the same floor. An empty rewrite, or one that matches the original after
normalising case, spacing and trailing punctuation, skips the second search. There are
at most two attempts. Only the email agent graph passes a `Reformulator`
(`email_service.reformulator`); `/rag/query` does not.

### 7.3 LLM provider

`get_llm()` in `app/llm/provider.py` is the single place a model is created. It is
cached and selected by `LLM_PROVIDER`:

- `ollama`: a local Ollama model named by `LLM_MODEL`. The config default is
  `gemma2:9b`; `backend/.env.example` sets `gemma2:2b`.
- `bedrock`: `ChatBedrockConverse` piped into `StrOutputParser`, so it returns plain
  text like Ollama. The model is `BEDROCK_MODEL_ID`, default
  `au.anthropic.claude-haiku-4-5-20251001-v1:0`, in `AWS_REGION` (default
  `ap-southeast-2`).

## 8. Access scopes

`access_scope` is derived from `doc_type` by `DOC_TYPE_TO_SCOPE` in
`app/rag/doc_scopes.py`. Both the upload path and the ingest scripts read it, so they
cannot disagree.

| access_scope | doc_types |
|---|---|
| general | registration_form, appointment_history, referral_letter, clinic_identity, policy_faq |
| restricted | consultation, consultation_note, pathology_report, prescription, care_plan, specialist_letter, hospital_discharge_summary, external_imaging_report |
| sensitive | consent_record, routing_rules, staff_directory, data_classification, guardrails |

An unknown `doc_type` falls back to `restricted`, never `general`, so an unrecognised
clinical document is not exposed to all staff.

The scopes a user may read come from `allowed_scopes()` in `app/auth/scoping.py`:
everyone gets `general`, and users with the `VIEW_CLINICAL` permission also get
`restricted`. No current caller grants `sensitive`, so those chunks are stored but not
retrievable.

## 9. Callers

- `POST /api/v1/rag/query` (`app/routes/rag.py`): requires `VIEW_CLINICAL` and passes
  `can_read_clinical()` (a doctor must be assigned to the patient). Builds the context
  from the caller's own scopes.
- `GET /api/v1/rag/documents`: lists the source documents behind a patient's
  retrievable chunks (`list_indexed_documents`), with the same checks. Org-wide chunks
  are excluded.
- Email reply drafting (`app/services/email_service.py`): uses `allowed_scopes=["general"]`
  only, either for the patient on the email's case or org-wide (`patient_id=None`), so
  restricted clinical content never reaches a drafted email.

## 10. Testing notes

- Retrieval tests (`tests/test_rag_retrieval.py`, `tests/test_rag_pipeline.py`) need
  Postgres with pgvector, which SQLite cannot provide. The Postgres test schema is
  built by `alembic upgrade head`.
- `pg_session` and `db_session` wrap each test in a transaction and roll it back. No
  fixture may drop shared schema, or `chunks` would be empty for every later RAG test.
  `seeded_chunks` also hides org-wide chunks, which the filter would otherwise add to
  every patient's results.
- Gate tests (`tests/test_rag_gating.py`) build `RetrievedChunk` objects with set scores
  and need no database: proceed, no results, below floor.
- Answer tests (`tests/test_rag_answer.py`) mock `app.rag.retrieval.retrieve` (patched
  on the module, because `retry.py` calls it through the module) and `get_llm()`. They
  check that the LLM is never called on `manual_handling` and that a refusal sentence
  with trailing whitespace maps to `refusal_source="llm"`.
- Embedding test doubles must implement `embed_query` and `embed_documents`. Never
  assert a self-match score of exactly 1.0 (see section 4).
- `pyproject.toml` sets `concurrency = ["greenlet"]` for coverage. Without it, async
  ORM code is under-reported.

To run the suite against a throwaway database, use `backend/scripts/run_tests_clean.sh`.
The CI steps are in `.github/workflows/backend-ci.yml`.

## 11. Environment

- `backend/.env.example` uses the Docker Compose service names (`db` for Postgres,
  `ollama` for Ollama). These resolve inside the Compose network only. When running
  scripts or tests from the host, use `localhost:5432` and `localhost:11434`, which
  `backend/docker-compose.yml` publishes.
- The embedding model is downloaded by sentence-transformers on first use, so the first
  ingest or query is slow.
