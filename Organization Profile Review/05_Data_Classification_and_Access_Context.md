<!-- doc_type: data_classification | access_scope: sensitive -->

# Data Classification and Access Context

Sensitive document. Grounds access decisions. Never surfaced to patients. Rewritten 2026-08-17 against the real `chunks.access_scope` vocabulary (`app/models/chunk.py`, `scripts/ingest_corpus.py::DOC_TYPE_TO_SCOPE`) and the real `ConsentStatus` enum (`app/models/consent.py`) — earlier revisions used a four-level Low/Medium/High/Critical classification mapped onto an invented `TIER_1_LOW`/`TIER_2_MEDIUM`/`TIER_3_HIGH` risk model. That risk model doesn't exist; see Contact Routing Rules for the real gate. This document now states classification purely in terms of the real access_scope column.

## Classification Levels

There are exactly three `access_scope` values, ratified in `DOC_TYPE_TO_SCOPE`, the single source of truth both ingestion and retrieval read from:

| Scope | Description |
| --- | --- |
| `general` | Non-sensitive, patient-facing. Reachable by both current retrieval callers (`/rag/query`, `email_service.draft_reply`) and safe to quote in a response. |
| `restricted` | Sensitive patient/clinical data. Reachable by an actor holding `VIEW_CLINICAL` via `/rag/query`, and always reachable by `draft_reply` (a drafted reply legitimately needs to reference the patient's own clinical content before human review). |
| `sensitive` | Internal-operations or highest-sensitivity data. Not reachable by any current retrieval caller — `app.auth.scoping.allowed_scopes()` never grants it, and `draft_reply` never requests it. Reserved for a future system-level caller (see `scripts/demo_rag.py::FULL_CTX`) that explicitly opts in. |

## Data Types and Classification

| Data type | Description | access_scope |
| --- | --- | --- |
| Appointment data | Booking details, schedules, time slots | `general` |
| General enquiries | Hours, services, non-sensitive queries | `general` |
| Patient basic information | Name, contact details, DOB | `general` |
| Referral documents | Referral forms and supporting documents | `general` |
| Patient medical records | Clinical history, diagnoses, notes | `restricted` |
| Clinical scans and results | Test results, imaging data | `restricted` |
| Prescription data | Medication-related records | `restricted` |
| Consent records | Patient consent and authorisation | `sensitive` |
| Payment information | Billing details, transactions | `sensitive` |
| Audit logs | System activity records | `sensitive` |
| Internal routing/staff/policy content (this corpus) | Routing rules, staff directory, guardrails, this document | `sensitive` |

Medicare/IRN/DVA numbers, private insurance details, and concession/HCC status are described in Clinic Identity and Policies & FAQ as registration policy, but the real `Patient` model does not currently store any of these fields (`mrn, name, dob, gender, status` only) — there is no `access_scope` to assign them because there is no column for them yet. See 00_Organisation_Profile_README.md's "What this corpus describes vs. what the schema stores today."

## Role-Based Access Context

| Role | Reaches `general`? | Reaches `restricted`? | Reaches `sensitive`? |
| --- | --- | --- | --- |
| FRONT_DESK | Yes | Only if granted `VIEW_CLINICAL` | No |
| OPERATOR | Yes | Only if granted `VIEW_CLINICAL` (example: operator02) | No |
| ADMIN | Yes | Only if granted `VIEW_CLINICAL` | No |
| DOCTOR | Yes | Yes, for assigned patients only (`doctor_patient_assignments`) | No |

`sensitive` is not reachable by any role today, granted or not — it is a scope no current retrieval caller requests, not a role permission. This is a deliberate gap: internal-grounding content (routing rules, staff directory, this document, guardrails) is ingested and ready, but nothing in the live pipeline consults it yet. That's future agentic work, not a bug in today's system.

## Per-User Grants and Row-Level Scoping

Two mechanisms modify the role baseline:

- **`VIEW_CLINICAL` grant.** A non-doctor granted `VIEW_CLINICAL` gains `restricted`-scope read across patients. This is a deliberate, logged exception used for tasks like referral triage (see operator02 in Staff Directory). It is a grant, not a role change.
- **Assigned-patient scoping.** A doctor's `restricted`-scope access is limited to patients in `doctor_patient_assignments`. This is row-level, enforced at query time (`app.auth.scoping.is_assigned`), not by role alone.

Do not widen `_security_filter` to resolve a vocabulary or scope mismatch from upstream data. Normalise at ingest instead (`DOC_TYPE_TO_SCOPE`). `doc_type` and `access_scope` are unconstrained `Text` columns today (no CHECK constraint — `app/models/chunk.py`'s own docstring says so), but they are still treated as a closed, ratified vocabulary by convention; an unmapped `doc_type` fails closed to `restricted`, never `general`.

## Consent States

`ConsentStatus` (`app/models/consent.py`) is scoped to an `intake_case`, not a patient directly:

| State | Meaning | System behaviour |
| --- | --- | --- |
| `PENDING` | Not yet captured (also the default for a request that can't establish consent) | Access proceeds subject to role and scope; nothing blocks on `PENDING` alone today |
| `CAPTURED` | Consent recorded and current | Access proceeds subject to role and scope |
| `WITHDRAWN` | Consent withdrawn | — |
| `NOT_REQUIRED` | Consent not applicable to this case | Access proceeds subject to role and scope |

There is no `CONSENT_UNCLEAR` state and no consent-driven HITL gate wired into retrieval today — consent is tracked per case for audit and process purposes, and does not currently gate `_security_filter` or the routing gate. If a future revision adds consent-based blocking, it should be stated here once it's real, not before.

## Access Control Rules

- **Least privilege.** Users reach only the data their role and grants require.
- **RBAC plus grants plus row-level scoping.** Access is the combination of all three, not role alone.
- **Data minimisation.** Only the data needed for the request is retrieved and displayed.
- **Audit logging.** Every `retrieve()` call writes a `retrieval.performed` audit event (`app/rag/retrieval.py::_emit_gov_retrieve_event`), regardless of scope.
- **Normalise at ingest, not at query.** A vocabulary mismatch from upstream data is fixed by the ingest-time mapping, never by widening `_security_filter`.

## Why This Matters

- Protection of sensitive patient data.
- Clear separation of responsibilities across roles.
- Alignment between what routing sends where and what each role may actually see.
- An honest record of what's live today (`general`/`restricted` via two retrieval callers) versus what's ingested but not yet consulted (`sensitive`), so nobody assumes this corpus is grounding decisions it structurally cannot reach yet.