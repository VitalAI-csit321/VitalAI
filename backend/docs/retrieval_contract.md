# FR-RAG-01 retrieval contract

`app/rag/retrieval.py::retrieve()` reads from whatever table backs the
`Chunk` model (`app/models/chunk.py`). Today that's the BASELINE table from
`alembic/versions/0005_baseline_chunks.py` (see
`docs/FR-RAG-01_handoff.md` for the reconciliation list). Whatever
replaces it — Matthew's ingestion schema included — must satisfy this
contract, or `retrieve()` needs to change, not just the table.

## The six fields

| Field | Type | Meaning | Used for |
|---|---|---|---|
| `patient_id` | UUID | The patient this chunk's content is about. | Security filter: `_security_filter` requires an exact match against `RetrievalContext.patient_id`. Every chunk must have exactly one owning patient — no shared/global chunks, no null. |
| `access_scope` | text | The governance tier that decides who may read this chunk, independent of what kind of document it is. | Security filter: `_security_filter` requires membership in `RetrievalContext.allowed_scopes`. This must never be derivable from `doc_type` — the two are separate axes on purpose (see divergence note below). |
| `doc_type` | text | What kind of document this chunk came from (clinical note, lab result, referral, billing, etc). | Optional exact-match filter in `retrieve(doc_type=...)`. Never used for security — a "billing"-labeled chunk and a "clinical_note"-labeled chunk can carry the same `access_scope`, or different ones; the label tells you nothing about who may read it. |
| `source_document_id` | UUID | Identifies the parent document a chunk was split from. | Provenance: returned on every `RetrievedChunk` so callers can cite/link back to the source document and group chunks that came from the same document. |
| `chunk_index` | int | This chunk's position within its source document (0-based). | Provenance/ordering: lets a caller reconstruct document order or deduplicate overlapping chunks from the same document. |
| `embedding` | vector(512) | The dense embedding of `content`, produced by `app.rag.embeddings.get_embedding_provider()`. | Similarity search: `retrieve()` ranks by `cosine_distance` against the query embedding. Must be exactly 512-dimensional — `retrieve()` asserts the *query* embedding's length and fails loud on mismatch, but a corpus embedded with a different provider/dimension will silently produce nonsense rankings instead of an error, since pgvector enforces `vector(512)` at insert time but says nothing about whether the vector actually came from the same model. |

`content` (text) is the seventh field carried through to `RetrievedChunk` — it's not part of the security or ranking contract, just the payload being ranked and returned.

## Non-negotiable invariant

`access_scope` and `doc_type` must remain independently governed. A
corpus generator is free to correlate them in practice (most `lab_result`
chunks might reasonably end up `restricted`), but the schema and the ingestion
pipeline must allow — and this repo's synthetic fixture deliberately
exercises — a chunk whose `doc_type` name would suggest one scope while its
actual `access_scope` says otherwise (see `ALICE_MENTAL_HEALTH_DOC` and
`ALICE_BILLING_DOC` in `scripts/synthetic_corpus/manifest.py`, and
`tests/test_rag_retrieval.py::test_divergence_filters_on_access_scope_not_doc_type`).
If a future ingestion schema collapses these into one column or makes one
derivable from the other, `_security_filter` breaks silently for exactly the
case this test exists to catch.

## What `retrieve()` does not check

- That `embedding` was produced by the *current* embedding provider/model
  version. If ingestion re-embeds with a different model without bumping
  something (a version column doesn't exist yet), rankings degrade silently
  rather than erroring.
- That `source_document_id` actually exists anywhere (no `documents` table to
  reference yet — see handoff doc, reconciliation item 5).
