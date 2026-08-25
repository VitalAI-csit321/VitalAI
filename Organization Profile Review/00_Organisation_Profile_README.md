# GreenCare Organisation Profile: Ingestion Manifest

This corpus is the demo grounding data for VitalAI. It describes a fictional clinic, GreenCare Family Medical Clinic, and the administrative rules the system operates under. Every document here is either patient-facing knowledge (safe to surface in responses) or internal policy (grounds behaviour, never echoed to patients).

## Canonical vocabulary (do not diverge)

These are not proposals. Every token below is the literal Postgres enum value or ratified constant in the real codebase, checked against source on 2026-08-17. Diverging from these breaks ingestion or grounds the assistant on facts that don't exist.

**System roles** (`app/models/user.py::UserRole`):

- `FRONT_DESK`
- `OPERATOR`
- `ADMIN`
- `DOCTOR`

"OPS", "Ops", "Back Office", "Operations" are display labels only. The system token is always `OPERATOR`. Do not ingest any other spelling.

**Task categories** (`app/models/task.py::TaskCategory`, 10 fixed values, no others exist):

`APPOINTMENT_REQUEST`, `NEW_PATIENT_ONBOARDING`, `PRESCRIPTION_RENEWAL`, `RESULTS_ENQUIRY`, `REFERRAL_REQUEST`, `MEDICAL_RECORDS_REQUEST`, `BILLING_INSURANCE_ENQUIRY`, `COMPLAINT_ESCALATION`, `GENERAL_ADMINISTRATIVE`, `URGENT_EMERGENCY`

**Consent states** (`app/models/consent.py::ConsentStatus`):

- `PENDING`
- `CAPTURED`
- `WITHDRAWN`
- `NOT_REQUIRED`

There is no "unclear" consent state. A request that can't establish consent stays `PENDING`.

**Chunk access scopes** (`app/models/chunk.py`, ratified in `scripts/ingest_corpus.py::DOC_TYPE_TO_SCOPE`):

- `general`
- `restricted`
- `sensitive`

Earlier drafts of this corpus used `public`/`internal`/`restricted` and a three-tier `TIER_1_LOW`/`TIER_2_MEDIUM`/`TIER_3_HIGH` risk model with an "85-point HITL gate". **Neither exists in the codebase.** They were invented for this corpus, not derived from it, and have been removed everywhere in this revision. See Contact Routing Rules and Guardrails for what the real routing/gate mechanism is.

## How org-wide content reaches RAG (resolved 2026-08-17)

`chunks.patient_id` was `NOT NULL`, and `_security_filter()` — the one function every retrieval call goes through — filtered on it exactly. That left no path for content that isn't tied to a patient, which is everything in this corpus except patient records.

Resolved by making `chunks.patient_id` nullable (`alembic/versions/0022_chunks_org_wide.py`): a `NULL` patient_id means "applies to every patient's retrieval context." `_security_filter` now matches `patient_id == ctx.patient_id OR patient_id IS NULL`, still gated by `access_scope` exactly as before — no security-filter logic was bypassed, just widened by one clause. Ingested by `scripts/ingest_org_profile.py`, a standalone script (not `ingest_corpus.py`, which assumes a UUID-named patient folder that this flat 6-file corpus doesn't have).

**access_scope reachability is not symmetric with the patient corpus.** The two real callers of `retrieve()` today are:

- `/rag/query` (`app/routes/rag.py`): `allowed_scopes` comes from `app.auth.scoping.allowed_scopes(actor)`, which is `{"general"}` plus `{"restricted"}` if the actor holds `VIEW_CLINICAL`. It never grants `"sensitive"`.
- `email_service.draft_reply` (patient-facing drafted email replies): hardcodes `allowed_scopes=["general", "restricted"]`. Also never includes `"sensitive"`.

Because `restricted` is the same tier real clinical patient data uses (consultation notes, prescriptions — content a drafted reply legitimately needs to reference), tagging the internal-only org docs `restricted` would make them reachable by both of the above, including the patient-facing draft path, with no existing guardrail term list covering staff usernames or internal routing text. So the four internal-grounding docs are tagged `sensitive` instead — a scope neither current caller ever requests, deliberately inert until a future system-level caller (see `scripts/demo_rag.py::FULL_CTX`, which already requests `["general", "restricted", "sensitive"]`) opts in explicitly. This keeps the clinical-data scope (`restricted`) and the internal-operations scope (`sensitive`) as two separate mechanisms, not one shared tier.

## Ingestion metadata

Each source document carries a `doc_type` and an `access_scope`. `doc_type` comes from the leading `<!-- doc_type: X -->` comment in each file. `access_scope` is **not** read from the file — `DOC_TYPE_TO_SCOPE` in `scripts/ingest_corpus.py` is the single source of truth for every doc_type in the system, patient and org-wide alike, so ingest and query can never drift apart. The table below reflects that mapping as of this revision; if it ever changes, the code is authoritative, not this table.

| File | doc_type | access_scope | Reachable by draft_reply / \`/rag/query\` today? |
| --- | --- | --- | --- |
| 01_Clinic_Identity.md | clinic_identity | general | Yes |
| 02_Policies_and_FAQ.md | policy_faq | general | Yes |
| 03_Contact_Routing_Rules.md | routing_rules | sensitive | No |
| 04_Staff_Directory.md | staff_directory | sensitive | No |
| 05_Data_Classification_and_Access_Context.md | data_classification | sensitive | No |
| 06_Communication_and_Guardrails.md | guardrails | sensitive | No |

Retrieval rule: `general` chunks are patient-facing and quotable. `sensitive` chunks ground internal behaviour and role decisions for future system-level tooling; no current retrieval caller can reach them, so they cannot appear in a patient-facing response today by construction, not by convention.

## Consistent facts across the corpus

If any of these change, update every file. They are referenced in more than one place.

- Clinic: GreenCare Family Medical Clinic, ABN 83 456 729 114
- Address: Suite 4, Level 2, 215 Liverpool Street, Sydney NSW 2000
- Phone: (02) 9123 4567, Email: reception@greencareclinic.com.au
- Doctors (6): Dr Aisha Rahman (doctor01, women's health), Dr David Nguyen (doctor02, chronic disease), Dr Priya Menon (doctor03, mental health/skin checks), Dr Marcus O'Connell (doctor04, men's health/sports medicine), Dr Hannah Fitzgerald (doctor05, paediatrics), Dr Samuel Osei (doctor06, aged care, waitlist only)
- The clinic is in-person only. No telehealth is offered or should be referenced.
- Front desk: Sarah Khan (frontdesk01), James Li (frontdesk02)
- Operators: Emily Carter (operator01), Daniel Singh (operator02)
- Admins: Michael Brown (admin01), Olivia Chen (admin02)

## What this corpus describes vs. what the schema stores today

Clinic Identity and Policies & FAQ describe appointment types/lengths, doctor weekly schedules, and registration fields (address, Medicare/IRN/DVA, insurance, emergency contact) as clinic policy. The registration fields are not invented: the real 5-step patient intake wizard (`PatientOnboardingPage.tsx`, frontend `master` branch) collects exactly this shape — name, DOB, gender, address, indigenous status, language, phone, email, emergency contact, medical history, insurance, Medicare, concession card. The gap is downstream of that: `createPatientFromOnboarding` (`api/cases.ts`) only actually sends `{name, dob, gender}` to `/api/v1/patients`, and the real `Patient` model only persists `mrn, name, dob, gender, status`. So the wizard collects this data today and the backend silently drops the rest before it's ever stored — a known frontend-backend persistence gap, not a fabricated process. The real `Appointment` model separately has no type/length/recurring-schedule/`get_availability()` — that part of Clinic Identity and Policies & FAQ genuinely is ahead of any UI or schema, tracked as the in-progress booking/calendar work.

## Decision log for this revision

1. `OPS` normalised to `OPERATOR` across routing and staff directory.
2. Telehealth removed entirely; the clinic is stated as in-person only.
3. Doctor roster expanded to 6, each with a special interest and weekly schedule.

## Revision 3 (2026-08-17): reconciled against real code

4. Removed the invented `public`/`internal`/`restricted` access_scope vocabulary and the `TIER_1_LOW`/`TIER_2_MEDIUM`/`TIER_3_HIGH` risk-tier model with its 85-point HITL gate — none of this exists in the codebase. Replaced with the real `general`/`restricted`/`sensitive` access_scope vocabulary and the real routing gate (a single LLM-confidence float vs. two thresholds, plus two hard overrides — see Contact Routing Rules).
5. Removed `CONSENT_VALID`/`CONSENT_INVALID`/`CONSENT_UNCLEAR`. Replaced with the real `ConsentStatus` states: `PENDING`/`CAPTURED`/`WITHDRAWN`/`NOT_REQUIRED`.
6. Rewrote the routing table in Contact Routing Rules against the real 10-value `TaskCategory` enum and the real category-to-role mapping in `app/services/task_routing_rules.py` (a direct one-role lookup, not the two-step "OPERATOR then DOCTOR" or the billing dispute/query split the earlier draft invented).
7. Resolved the structural blocker that made this corpus unable to reach RAG at all: `chunks.patient_id` is now nullable, `NULL` = org-wide. See "How org-wide content reaches RAG" above.
8. Re-derived the `doc_type` → `access_scope` mapping against the real reachability of `retrieve()`'s two current callers, splitting clinical-patient-data scope (`restricted`) from internal-operations scope (`sensitive`) rather than reusing one tier for both.

## Open items (unchanged, still open)

- Fee values are placeholders.
- Whether the demo surfaces per-user grants (`VIEW_CLINICAL`) at all in the presentation path, or stays documented but unused.
- Booking (appointment types/lengths/availability) has no backing UI or schema yet — in-progress work, tracked separately.
- Registration fields (address/Medicare/insurance/emergency contact) are already collected by the real intake wizard but dropped before reaching the backend (`Patient` only persists `mrn, name, dob, gender, status`) — a frontend-backend persistence gap, tracked separately, not by this corpus.