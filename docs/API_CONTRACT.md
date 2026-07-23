# VitalAI — Frontend ↔ Backend Wiring Contract

This is the reference the frontend is built against. Every endpoint here is live
and covered by the end-to-end smoke test. Generated from the merged tree
(main + fix/ci-pipeline + feature/fr-rag-retrieval).

## Base

- **Base URL (dev):** `http://localhost:8000`
- **API prefix:** `/api/v1` (health is un-prefixed at `/health`)
- **Auth:** JWT bearer. Send `Authorization: Bearer <token>` on everything except
  `/health`, `/`, `/api/v1/auth/login`, and `/api/v1/auth/register`.
- **CORS:** `http://localhost:5173` and `http://127.0.0.1:5173` are allowed with
  credentials. Change via `CORS_ORIGINS` env (comma-separated, no `*`).

## The one gotcha: login is form-encoded, not JSON

`POST /api/v1/auth/login` uses OAuth2's password form. It does **not** take JSON,
and the email goes in a field called `username`:

```
Content-Type: application/x-www-form-urlencoded
username=<email>&password=<password>
```

Returns `{ "access_token": "...", "token_type": "bearer" }`. Rate-limited to
5/minute. Every other endpoint is JSON.

## Pagination envelope

Every list endpoint returns:

```json
{ "items": [...], "total": 123, "limit": 25, "offset": 0 }
```

Query params: `limit` (1–100, default 25), `offset` (≥0). Build one table +
pager component and reuse it on every page.

## Roles

Three roles: `front_desk`, `ops_manager`, `admin`. Register always creates a
`front_desk` user (the `role` field in the register body is ignored by design);
elevation is admin-only.

---

## Page → endpoint map

### Login
- `POST /api/v1/auth/login` — form-encoded (see above)
- `GET /api/v1/auth/me` — current user, for the header/profile

### Dashboard Overview
- `GET /api/v1/intake/summary` → `{ status_counts: { <status>: n } }` — the tiles
- `GET /api/v1/intake?limit=&offset=&status=&channel=&search=` — recent cases table
- `GET /api/v1/review-tasks/summary` → `{ open_counts: { <task_type>: n } }` — queue badges
- `GET /api/v1/routing/summary` → `{ queue_counts: { <queue>: n } }` — escalation counts

`status` repeats for OR (`?status=triage_immediate&status=triage_time_sensitive`).

### Patient Onboarding (intake)
- `POST /api/v1/intake` — `{ patient_name, contact_reason, contact_channel, notes? }` → 201
- `GET /api/v1/intake/{case_id}` — one case
- `PATCH /api/v1/intake/{case_id}/status` — `{ status }` — **ops_manager / admin only**

### Consent Capture
- `POST /api/v1/consent` — `{ case_id, consent_type?, notes? }` → 201 (creates pending)
- `GET /api/v1/consent/by-case/{case_id}` — latest consent for a case
- `POST /api/v1/consent/{consent_id}/capture` — pending → captured (409 if not pending)
- `POST /api/v1/consent/{consent_id}/withdraw` — → withdrawn

**Flow rule the UI must respect:** triage is refused (422) until consent is
`captured`. Onboarding → consent → capture must happen before the triage button
is enabled.

### Triage + routing (usually behind onboarding, not always its own page)
- `POST /api/v1/triage` — `{ case_id, contact_reason, keywords?, patient_priority_flags? }`
  → `{ triage_id, category, confidence, rationale, routing_action, target_queue, escalated }`.
  Returns **422** if consent isn't captured.
- `POST /api/v1/routing` — `{ triage_id }` → persists the routing decision (201)

### Administrative Review Queue
- `GET /api/v1/review-tasks?status=&task_type=&assigned_to=&case_id=&limit=&offset=`
- `POST /api/v1/review-tasks` — `{ case_id, task_type, triage_id?, notes? }` → 201
- `GET /api/v1/review-tasks/{task_id}`
- `PATCH /api/v1/review-tasks/{task_id}` — `{ status?, assigned_to?, notes? }`
  — **ops_manager / admin only**. Illegal state moves return 409
  (e.g. completed → in_progress). Legal: pending→in_progress→completed, or
  →cancelled from either open state. Terminal states don't reopen.
- `GET /api/v1/review-tasks/summary` — open counts per type

`task_type`: `triage_review`, `consent_review`, `escalation_review`.
`status`: `pending`, `in_progress`, `completed`, `cancelled`.

### Escalation Routing Board
- `GET /api/v1/routing?target_queue=&action=&escalated=&limit=&offset=` — ordered
  escalated-first, then oldest (waiting escalations float to the top)
- `GET /api/v1/routing/summary` — decisions per queue (the board columns)
- `GET /api/v1/routing/by-case/{case_id}` — a case's routing

Queues seen so far: `escalation_immediate`, `priority_review`,
`low_confidence_review`, `admin_routine`.

### Record & Information Retrieval (RAG)
- `POST /api/v1/rag/query` — `{ patient_id, question, k?, doc_type? }` →
  `{ answer, refusal_source, decision, sufficient, reason, confidence,
     confidence_source, top_score, citations: [...] }`

`refusal_source`: `none` (answered), `gate` (deterministic sufficiency/confidence
refusal, no LLM called), `llm` (model declined from context). The UI should show
citations and, when `refusal_source != none`, the "not enough information" state
rather than a fabricated answer.

**⚠ Two open items — see `backend/docs/FR-RAG-01_handoff.md`.** `patient_id` is
supplied by the caller because no case→patient link exists in the schema yet, so
this endpoint can't yet verify the caller has any business reading that patient.
Treat this page as **synthetic-data-only** until that link lands. Requires a
Postgres+pgvector DB and a running embedding provider; returns 503 if either is
unavailable.

### Audit Logs & Activity
- `GET /api/v1/audit?action=&actor_id=&case_id=&since=&until=&limit=&offset=`
  — **admin only**. Newest first.
- `GET /api/v1/audit/actions` — distinct action values, for the filter dropdown
- `GET /api/v1/audit/by-case/{case_id}` — one case's trail

`since`/`until` are ISO-8601 datetimes. The log is append-only (DB-enforced) — no
edit/delete endpoints exist by design.

### User Management (RBAC)
- `GET /api/v1/auth/users?role=&is_active=&search=&limit=&offset=` — **admin only**
- `POST /api/v1/auth/register` — `{ email, password (8–128), full_name }` → 201
  (always creates front_desk)
- `POST /api/v1/auth/users/{user_id}/elevate` — `{ new_role }` — **admin only**
- `POST /api/v1/auth/users/{user_id}/deactivate` — **admin only**; 409 on self
- `POST /api/v1/auth/users/{user_id}/reactivate` — **admin only**

Users are deactivated, never deleted — they're referenced by the append-only
audit trail.

---

## Pages with NO backend yet (do not build against these)

- **Messages & Email** — no model, no route. Needs a product decision before any
  endpoint exists. Don't scaffold data-bound UI here.
- **Appointment booking** — a model exists on `feature/appointment-model` but it's
  intentionally **not merged**: it references a `doctor` role that isn't in
  `UserRole`, ships no migration, and has no routes. It cannot run as-is.
  Merging it is a scoping decision (add doctor role + migration + booking
  endpoints), not a wiring task.

## Branches

- **Merged into this tree:** `fix/ci-pipeline` (pgvector CI image + JWT secret +
  Postgres-from-Alembic conftest), `feature/fr-rag-retrieval` (vector retrieval,
  gates, grounded answers).
- **Superseded — close it:** `fix/ci-jwt-secret`. Its workflow file is
  byte-identical to `fix/ci-pipeline`'s; ci-pipeline strictly contains it.
- **Not merged:** `feature/appointment-model` (see above).
