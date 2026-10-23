# Retrieval contract (FR-RAG-01)

`app/rag/retrieval.py::retrieve()` reads the `chunks` table (`app/models/chunk.py`).
Anything that writes chunks (`scripts/ingest_corpus.py`, `scripts/ingest_org_profile.py`,
and clinical document upload through `app/services/clinical_document_service.py`) must
satisfy this contract, or `retrieve()` needs to change, not just the table.

## The fields

| Field | Type | Meaning | Used for |
|---|---|---|---|
| `patient_id` | UUID, nullable | The patient this chunk's content is about. NULL marks an org-wide chunk (clinic policy, routing rules, guardrails) that applies to every patient. | Security filter: `_security_filter` matches `patient_id = RetrievalContext.patient_id OR patient_id IS NULL`. |
| `access_scope` | text | The governance tier that decides who may read this chunk: `general`, `restricted` or `sensitive`. | Security filter: `_security_filter` requires membership in `RetrievalContext.allowed_scopes`. |
| `doc_type` | text | What kind of document this chunk came from (`consultation_note`, `pathology_report`, `consent_record`, ...). | Optional exact-match filter in `retrieve(doc_type=...)`. Never used for security. |
| `source_document_id` | UUID | The parent document a chunk was split from. | Provenance: returned on every `RetrievedChunk` so callers can cite the source and group chunks from the same document. |
| `citation_tag` | text, nullable | A short source label: the first 8 characters of the patient id plus the `doc_type` (`org_<doc_type>` for org-wide chunks). | Provenance. |
| `chunk_index` | int | This chunk's position within its source document (0-based). | Ordering and de-duplication. |
| `embedding` | vector(512) | The dense embedding of `content`, from `app.rag.embeddings.get_embedding_provider()` (local `nomic-embed-text`, truncated to 512 dimensions). | Vector search and the score. Must be exactly 512-dimensional. |
| `search_vector` | tsvector, computed | `to_tsvector('english', content)`, filled in by Postgres (migration `0023`). | Full-text half of hybrid search. Writers never set it. |

`content` (text) is the payload being ranked and returned.

## Ranking

The default strategy is `hybrid`: a vector query (cosine distance) and a Postgres full-text
query run separately, both through `_security_filter`, and their ranked lists are fused
with Reciprocal Rank Fusion. Fusion decides which chunks make the top k and their order.
`RetrievedChunk.score` is always the cosine similarity, never the fused score, so the
sufficiency gate (`app/rag/gating.py`, `sufficiency_floor` 0.44) keeps the meaning it was
calibrated against. `strategy="vector"` runs the vector query alone.

## Invariant: access_scope is not doc_type

Both ingestion paths derive `access_scope` from `doc_type` through one mapping,
`app/rag/doc_scopes.py`, and an unknown `doc_type` fails closed to `restricted`. The
schema still keeps them as separate columns, and the security filter reads only
`access_scope`. The synthetic test fixture deliberately stores chunks whose `doc_type`
suggests one scope while `access_scope` says another (`ALICE_MENTAL_HEALTH_DOC` and
`ALICE_BILLING_DOC` in `scripts/synthetic_corpus/manifest.py`), and
`tests/test_rag_retrieval.py::test_divergence_filters_on_access_scope_not_doc_type`
proves the filter follows `access_scope`. Collapsing the two columns would break that
test, which is the point of it.

## What `retrieve()` does not check

- That `embedding` came from the current embedding model. There is no model version
  column, so re-embedding with a different model degrades rankings silently instead of
  failing. `retrieve()` does check the query embedding's length.
- That `source_document_id` exists. It is a soft reference to `clinical_documents` with
  no foreign key, because chunks from the synthetic corpus have no row there.
