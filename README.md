# VitalAI

VitalAI is a healthcare administration platform. It handles patient intake, consent,
triage, task and communication routing, appointments, clinical document storage, and an
audit trail that proves nothing was changed after the fact. It also includes a
retrieval-based question answering feature that lets clinical staff ask a question over a
patient's stored records and get an answer that cites the exact source document.

The system does not provide clinical decision support, diagnosis, or treatment advice.
It is an administrative and record-keeping platform. Where it shows clinical text back
to a user, it displays the record as written. It does not interpret or summarize it.

## What the system does

- **Patient intake and consent.** Front desk staff register patients, open intake cases,
  and capture consent before any clinical action proceeds.
- **Triage and routing.** Cases are classified by urgency and routed to the right queue.
  Every decision is recorded.
- **Email and call pipeline.** Incoming emails and calls both go through the same
  classifier and the same routing rules, so an email and a phone call that mean the same
  thing end up in the same place. See "Email and call pipeline" below for detail.
- **Role-based access control.** Four roles (front desk, operator, admin, doctor), a
  permission system checked on every route, and row-level scoping so a doctor only sees
  their own assigned patients.
- **Human-in-the-loop approval.** Nothing an automated process proposes takes effect
  until a human with the right permission approves it.
- **Audit trail.** Every state-changing action, and every read of the audit log itself,
  is recorded. The audit table is append-only at the database level: no application
  code, including an administrator account, can edit or delete a row. A hash chain over
  the events lets anyone verify the log has not been tampered with.
- **Appointments.** Booking, rescheduling, and cancellation, with doctors restricted to
  their own calendar.
- **Clinical document upload and retrieval-based Q&A.** Upload a text-based PDF, extract
  and index its content, and ask natural language questions over it. The system only
  answers from retrieved content it has actual evidence for. If it does not have enough
  information, it says so instead of guessing.
- **Dashboard.** A web frontend covering intake, consent, patients, review queue,
  escalations, records search, audit log, and user management.

## Email and call pipeline

Every incoming email (`POST /api/v1/email/ingest`) and every logged call
(`POST /api/v1/calls`) is classified by one shared classifier
(`app/services/content_classifier.py`) into one of ten categories: appointment request,
new patient onboarding, prescription renewal, results enquiry, referral request, medical
records request, billing or insurance enquiry, complaint or escalation, general
administrative, or urgent/emergency.

The classifier also returns a confidence score. That score decides what happens next:

| Confidence | Outcome |
|---|---|
| 0.90 and above | Routed automatically, no human involved |
| 0.70 up to 0.90 | Routed automatically, flagged for an audit sample |
| Below 0.70 | Sent to the human review queue instead of being routed automatically |

Two things skip this scoring entirely and always go straight to a human: any content
flagged urgent or emergency, and anything classified as a complaint or escalation.

Once a category is assigned, it resolves to the role that should handle it (front desk,
operator, or doctor) and becomes a task. From there:

- `POST /api/v1/tasks/{id}/override`, `/escalate`, and `/archive` let an authorized user
  change the outcome, with the reason recorded.
- `POST /api/v1/tasks/{id}/comments` and `GET /api/v1/tasks/{id}/comments` hold a
  discussion thread on the task, for example between the person who escalated it and the
  person who picks it up.
- `GET /api/v1/inbox` shows the unified queue of email- and call-based tasks together.
- `GET /api/v1/human-review` is the queue for anything the confidence gate did not route
  automatically, with claim, complete, reject, and escalate actions on each item.

A call still needs a transcript before this pipeline can classify it. Speech-to-text
itself is out of scope for this project; calls are logged with their transcript already
attached.

## Repository layout

`main` is a monorepo: it carries both the backend and the frontend, so one checkout runs
the whole application.

```
main
├── backend/            FastAPI service, database, tests
└── frontend/frontend/  React application
```

This was not always true. The backend and frontend were built and versioned separately, on
two branches with no shared git history: `main` held the backend with an empty `frontend/`
placeholder, and `master` held the real frontend plus a stale copy of the backend that
could not serve it. They were consolidated onto `main` in August 2026. `master` is retained
but archival, frozen at the tag `archive/master-final`; do not start new work there.

See "Frontend" below for how to run the React application.

### Full directory tree

```
/
├── README.md                      this file
├── WORKLOG.md                     running development log
├── DEMO_PRESENTATION.md           demo script and talking points
├── rag_knowledge.md               retrieval and question-answering design notes
├── VitalAI RBAC Report - Audit Trail.md   the access control specification
├── docs/
│   └── backend_gap_analysis.md    page-by-page design decisions (Patients, Audit, Consent, Records, Users)
├── .github/
│   └── workflows/
│       ├── backend-ci.yml         backend lint, type check, and test pipeline
│       └── frontend-ci.yml        frontend lint and type-checked build
├── frontend/                      real Vite + React SPA at frontend/frontend/, see "Frontend" above
│
└── backend/
    ├── README.md                  full backend setup guide and API endpoint table
    ├── Dockerfile
    ├── docker-compose.yml         api, db (Postgres+pgvector), redis, minio, ollama, adminer
    ├── docker-entrypoint-initdb.d/01_pgvector.sql   enables the pgvector extension on first boot
    ├── requirements.txt           dependency versions used in development
    ├── requirements.lock          pinned versions for reproducible installs
    ├── pyproject.toml             ruff and mypy configuration
    ├── pytest.ini
    ├── alembic.ini
    │
    ├── alembic/versions/          25 migrations, in order: initial schema and the append-only
    │                              audit trigger, triage/routing, the vector store, human review
    │                              tasks, appointments, RBAC roles and permission grants, patients,
    │                              doctor-patient assignments, clinical documents, user department,
    │                              approval requests, the audit hash chain, calls and tasks,
    │                              task comments, and the email/call/task unification
    │
    ├── app/
    │   ├── main.py                 FastAPI app, router registration, middleware
    │   ├── config.py                all settings, env-driven (pydantic-settings)
    │   ├── database.py              async engine and session factory
    │   ├── audit_context.py         request-scoped IP and session id capture for audit logging
    │   ├── limiter.py                login rate limiting
    │   │
    │   ├── models/                  SQLAlchemy tables: user, patient, case, consent, triage,
    │   │                            routing, appointment, clinical_document, chunk, audit,
    │   │                            approval, assignment, human_review, email, call, task,
    │   │                            task_comment, permission_grant
    │   │
    │   ├── schemas/                 Pydantic request and response models, one file per domain,
    │   │                            same names as models/
    │   │
    │   ├── routes/                  API handlers, one file per domain: health, auth, intake,
    │   │                            consent, triage, routing, patients, assignments,
    │   │                            appointments, clinical_documents, rag, audit, approvals,
    │   │                            human_review, email, calls, tasks, inbox, llm
    │   │
    │   ├── services/                business logic behind the routes: intake, consent, triage,
    │   │                            routing_rules, routing, patient, assignment, appointment,
    │   │                            clinical_document, audit, approval, human_review, email,
    │   │                            call, task, content_classifier (shared email/call
    │   │                            classifier), task_routing_rules, task_routing_gate,
    │   │                            doctor_suggestion, permission, user, rag_service
    │   │
    │   ├── auth/                    security.py (JWT), dependencies.py (require_permission,
    │   │                            require_roles), permissions.py (role-to-permission map),
    │   │                            rbac_registry.py (reads live routes for the RBAC test
    │   │                            suite), scoping.py (row-level doctor scoping helpers)
    │   │
    │   ├── llm/                     provider.py (get_llm, switches Ollama/Bedrock),
    │   │                            guardrail.py (input guardrail on every LLM call),
    │   │                            output_guardrail.py (blocks restricted terms in drafts)
    │   │
    │   ├── rag/                     retrieval.py, retriever.py, embeddings.py, chunking.py,
    │   │                            gating.py (sufficiency/confidence thresholds), answer.py
    │   │                            (grounded answer synthesis), text_extraction.py (PDF text)
    │   │
    │   └── agents/                  triage_agent.py, rag_agent.py (reserved for a future
    │                                agent-based classifier, not wired in yet)
    │
    ├── tests/                      67 test files, one per service/route/model pair above,
    │                              plus test_rbac_enforcement.py (every route x every role)
    │                              and test_audit_trigger.py (proves the audit log is
    │                              genuinely append-only against real Postgres)
    │
    ├── scripts/
    │   ├── ingest_corpus.py         chunks, embeds, and indexes the demo corpus
    │   ├── seed_demo_patients.py    creates matching patient rows for the demo corpus
    │   ├── seed_synthetic_chunks.py
    │   ├── demo_query.py / demo_rag.py   command-line RAG smoke tests
    │   └── synthetic_corpus/        a small hand-written fixture patient (Alice) used in tests
    │
    ├── ingestion/matthew_corpus/    100 synthetic patient folders, 5 documents each
    │                              (registration form, appointment history, prescription,
    │                              consultation note, pathology report), used by
    │                              scripts/ingest_corpus.py for the demo dataset
    │
    └── Dataset Generator Code/     the script that produced the synthetic corpus above
```

## Frontend

The frontend lives at `frontend/frontend/`, a Vite + React + TypeScript single-page app,
brought onto this branch from `master` as part of the monorepo consolidation. It talks to
the backend over the REST API documented in `backend/README.md`.

### Running it

```bash
cd frontend/frontend
cp .env.example .env      # VITE_API_BASE_URL=http://localhost:8000
npm install
npm run dev                # http://localhost:5173
```

`npm run build` type-checks with `tsc -b` (TypeScript strict) and then runs `vite build`,
emitting a production bundle to `dist/`. `npm run lint` runs ESLint over the project. See
"Frontend" under Getting started below for what to do if Vite picks a port other than
5173.

### Screens

Two route shells, defined in `src/App.tsx`:

**Main app:** Login, Forgot password, Dashboard, Patients list, Patient onboarding,
Patient detail, Case detail, Consent queue, Consent capture, Consent success, Records
(retrieval-based Q&A), Inbox, Compose, Review queue, Add case, Escalations (with a detail
view), Calendar and appointments (list, new, detail, edit), and Settings. Audit log,
Audit event detail, and Users are gated to the `admin` role and hidden from the sidebar
for other roles.

**Platform Operations:** a second shell with its own login (`/platform-ops/login`),
covering System Health and Model & Risk Configuration. It shares the same auth session as
the main app but renders its own layout (`PlatformOpsLayout`, in
`src/pages/PlatformOps.tsx`).

`frontend/frontend/README.md` additionally documents a `src/api/_placeholder.ts` seam for
the handful of fields not yet backed by a real endpoint (the dashboard's weekly chart, the
consent-form label rotation, and the forgot-password and platform-ops auth flows); that
detail did not change during this merge, so read it there if you're wiring up new backend
fields.

## Tech stack

**Backend:** Python 3.13, FastAPI, async SQLAlchemy, Alembic, PostgreSQL with pgvector,
Redis, MinIO for object storage, JWT authentication. LLM calls go through a provider
abstraction that switches between Ollama (local, for development) and AWS Bedrock
(staging and production) using one environment variable. Adminer is included for browsing
the database in a browser.

**Frontend:** React, TypeScript, Vite, Tailwind CSS, React Router, TanStack Query.

**Testing and CI:** pytest, ruff, mypy, GitHub Actions.

## Getting started

### Prerequisites

- Docker and Docker Compose
- Git
- Node.js 18 or later, for the frontend
- Python 3.13, only needed if you want to run the backend outside Docker

### Backend

The backend lives on this branch, under `backend/`.

```bash
cd backend
cp .env.example .env
```

Open `.env` and set `JWT_SECRET_KEY` to a real generated value. Do not leave the
placeholder in place.

```bash
python -c "import secrets; print(secrets.token_urlsafe())"
```

Start everything with Docker Compose:

```bash
docker compose up --build
docker compose exec api alembic upgrade head
```

The API is now running at `http://localhost:8000`. Interactive API docs are at
`http://localhost:8000/docs`.

Pull the local LLM model once, so the question answering feature has something to call:

```bash
docker compose exec ollama ollama pull gemma2:9b
```

Full backend setup, including running without Docker, the environment variable
reference, and the complete API endpoint table, is documented in
[backend/README.md](backend/README.md).

### Frontend

The frontend is checked in on this branch at `frontend/frontend/`; see "Frontend" above
for install and run steps. Keep the backend running in one terminal and the frontend dev
server in a second, since the frontend needs the API to already be up.

Open the URL Vite prints in the terminal. By default that is `http://localhost:5173`.
The frontend talks to the API at `http://localhost:8000` by default (set in the `.env`
file you just copied), and the backend already allows requests from `http://localhost:5173`
by default, so no extra configuration is needed.

If port 5173 is already taken on your machine, Vite will start on the next free port
instead (5174, 5175, and so on) and print whichever one it used. If that happens, login
requests will fail silently with a CORS error in the browser console, because the backend
only trusts 5173 by default. Fix it by adding the actual port to `CORS_ORIGINS` in
`backend/.env` (comma-separated, both `http://localhost:...` and `http://127.0.0.1:...`
forms) and restarting the `api` container.

### Creating the first account

The frontend has a login page but no public sign-up page. Every account is created by an
admin, and the very first admin has to be created by hand, since there is no bootstrap
step that does it automatically.

1. Open `http://localhost:8000/docs`, find `POST /api/v1/auth/register`, click
   "Try it out," and register yourself with a real email, a password of at least 8
   characters, and your name. This always creates a `front_desk` account regardless of
   what role you send.
2. Promote that account to admin directly in the database:

   ```bash
   docker compose exec db psql -U vitalai -d vitalai \
     -c "UPDATE users SET role = 'admin' WHERE email = 'you@example.com';"
   ```

3. Go to the frontend's login page and log in with that email and password.

From here, use this admin account to create everyone else, either from the Users page in
the frontend or by calling `POST /api/v1/auth/users/{user_id}/elevate`.

## Browsing the database

Adminer is included in `docker-compose.yml` so you can look at the actual tables in a
browser, without installing anything or writing SQL by hand.

```bash
docker compose up -d adminer
```

Open `http://localhost:8080` and log in with:

| Field | Value |
|---|---|
| System | PostgreSQL |
| Server | `db` |
| Username | `vitalai` |
| Password | `vitalai` |
| Database | `vitalai` |

Use `db` as the server, not `localhost`. Adminer runs inside the same Docker network as
the database and reaches it by the service name, the same way the API container does.

## Running tests

```bash
cd backend
docker compose up -d db minio
pytest
```

Most of the suite runs against an in-memory database and needs nothing extra. A handful
of tests need real Postgres and MinIO, which is what `docker compose up -d db minio`
provides. Without them, the affected tests fail with connection errors instead of
skipping.

Lint and type checks, both required in CI:

```bash
ruff check app tests
mypy app
```

Full detail, including how to run the audit log tamper-detection tests specifically, is
in `backend/README.md`.

## Documentation

- [backend/README.md](backend/README.md): full backend setup, environment variables, and
  the complete API endpoint table.
- `VitalAI RBAC Report - Audit Trail.md`: the access control design, roles, permissions,
  and which role can do what.
- `docs/backend_gap_analysis.md`: the design decisions behind the Patients, Audit,
  Consent, Records, and Users pages.
- `rag_knowledge.md`: how the retrieval and question answering pipeline works, and where
  its data comes from.

## Known limitations

- The triage classifier matches on keywords and has no negation handling, so a phrase
  like "no chest pain" still escalates. This is a deliberate fail-safe choice: it
  over-escalates rather than risks missing something urgent.
- Email and call classification into a task category uses a confidence threshold.
  Anything below it goes to a human review queue instead of being routed automatically.
- This system is for administrative record keeping. It gives no diagnosis or treatment
  advice, and clinical judgment stays with the clinician at every step.