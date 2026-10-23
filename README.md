# VitalAI

VitalAI is a healthcare administration platform for a GP clinic. It handles patient
intake, consent, triage, the clinic's email and phone messages, appointments, clinical
document storage, and an audit trail that proves nothing was changed after the fact. It
also includes a retrieval-based question answering feature that lets clinical staff ask a
question over a patient's stored records and get an answer that cites the exact source
document.

The system does not provide clinical decision support, diagnosis, or treatment advice.
It is an administrative and record-keeping platform. Where it shows clinical text back
to a user, it displays the record as written. It does not interpret or summarize it.

All data in this repository is synthetic. `SYNTHETIC_ONLY=true` is the default, and the
application refuses to start with `APP_ENV=production` while it is set.

## Team

CSIT321 capstone project.

| Member ID | Name |
|---|---|
| 8738798 | Afra Nawar Anchal |
| 8915805 | Ahnaf Jubayer Islam |
| 8668863 | Ariana Nozari |
| 8439394 | Kartik Kartik |
| 8132574 | Matthew Trueman |
| 8782957 | Md Aminul Islam Rupom |

## What the system does

- **Patient intake and consent.** Front desk staff register patients, open intake cases,
  and capture consent before any clinical action proceeds. A new patient can also be sent
  a link to a web registration form.
- **Cases.** A patient's contacts, appointments and consents are grouped into cases
  (episodes of care) that staff can open, close and reopen.
- **Triage and routing.** Cases are classified by urgency and routed to the right queue.
  Every decision is recorded.
- **Email, call and voicemail pipeline.** Incoming emails, logged calls and voicemails all
  go through the same classifier and the same routing rules, so an email and a phone call
  that mean the same thing end up in the same place. See "Email and call pipeline" below.
- **Email agent.** Behind feature flags that are off by default, an agent identifies the
  sender, drafts a reply grounded in the clinic's own documents, checks the draft, and can
  book an appointment over a short email conversation. See "The email agent" below.
- **Review Queue.** Everything that needs a person (a message the classifier was unsure
  of, an unidentified sender, a held draft, a prescription request) lands in one queue.
- **Role-based access control.** Four roles (front desk, operator, admin, doctor), a
  permission system checked on every route, per-user permission grants, and row-level
  scoping so a doctor only sees their own assigned patients.
- **Human approval of replies.** A drafted reply waits for a person with the right
  permission to approve, edit or reject it. The exceptions are explicit switches,
  described under "The email agent".
- **Audit trail.** Every state-changing action, and every read of the audit log itself,
  is recorded. The audit table is append-only at the database level: no application
  code, including an administrator account, can edit or delete a row. A hash chain over
  the events lets anyone verify the log has not been tampered with.
- **Appointments.** Booking, rescheduling, completion and cancellation on a calendar,
  with doctors restricted to their own. Bookings are refused outside clinic hours
  (8am to 6pm, `Australia/Sydney`), on weekends and on NSW public holidays.
- **Clinical document upload and retrieval-based Q&A.** Upload a text-based PDF, extract
  and index its content, and ask natural language questions over it. The system only
  answers from retrieved content it has actual evidence for. If it does not have enough
  information, it says so instead of guessing.
- **Web frontend.** Dashboard, patients, cases, consent, inbox, review queue,
  escalations, calendar, records search, audit log, user management and settings.

## Email and call pipeline

Every incoming email (`POST /api/v1/email/ingest`, or the Outlook mailbox when it is
connected) and every logged call (`POST /api/v1/calls`) is classified by one shared
classifier (`app/services/content_classifier.py`) into one of ten categories: appointment
request, new patient onboarding, prescription renewal, results enquiry, referral request,
medical records request, billing or insurance enquiry, complaint or escalation, general
administrative, or urgent/emergency.

The classifier also returns a confidence score. That score decides what happens next:

| Confidence | Outcome |
|---|---|
| 0.90 and above | Routed automatically, no human involved |
| 0.70 up to 0.90 | Routed automatically, flagged for an audit sample |
| Below 0.70 | Sent to the Review Queue instead of being routed automatically |

Two things skip this scoring entirely and always go straight to a human: any content
flagged urgent or emergency, and anything classified as a complaint or escalation.

Once a category is assigned, it resolves to the role that should handle it (front desk,
operator, or doctor) and becomes a task. From there:

- `POST /api/v1/tasks/{id}/override`, `/escalate`, and `/archive` let an authorized user
  change the outcome, with the reason recorded.
- `POST /api/v1/tasks/{id}/comments` and `GET /api/v1/tasks/{id}/comments` hold a
  discussion thread on the task, for example between the person who escalated it and the
  person who picks it up.
- `GET /api/v1/inbox` shows the unified queue of email- and call-based tasks together,
  and `POST /api/v1/inbox/{id}/reply` sends a reply a person wrote themselves.
- `GET /api/v1/human-review` is the Review Queue, with claim, complete, reject, escalate,
  reroute, reassign and link-patient actions on each item.

**Calls and voicemail.** A call can be logged with its transcript already attached, or
its audio can be transcribed on the server with Whisper (`POST /api/v1/calls/transcribe`).
A voicemail line over Twilio is included but off by default (`TWILIO_ENABLED=false`);
`POST /api/v1/voicemails/simulate` runs the same voicemail pipeline without Twilio.
`backend/README.md` has the Twilio setup steps.

### The email agent

The agent is a LangGraph graph in `backend/app/agents/`. Each part has its own switch in
`backend/.env`, and every switch that sends mail or acts without a person is off unless
you turn it on:

| Setting | Default | What it turns on |
|---|---|---|
| `AGENTIC_PIPELINE_ENABLED` | off | The agent handles incoming email: identifies the sender, retrieves from the clinic's documents, drafts a reply, and a second pass checks the draft |
| `EMAIL_BOOKING_CONVERSATION_ENABLED` | off | Multi-turn email conversations: an identity check, then offered times, then the booking. Its templated emails and the booking itself happen with no person approving them |
| `PATIENT_FORM_LINK_ENABLED` | off | An unknown sender who asks to book or register is sent a link to the web registration form. Needs both settings above |
| `EMAIL_AUTO_SEND_ENABLED` | on | The master switch for any reply leaving without approval. Off holds everything for a person |
| `INTENT_CHECK_ENABLED` | off | A computed second opinion on the classifier's category; a disagreement sends the email to a person |
| `APPOINTMENT_REMINDERS_ENABLED` | off | Reminder emails before an appointment |
| `OUTLOOK_ENABLED` | off | Reads the clinic mailbox through Microsoft Graph |

Replies about prescriptions, results and referrals never send without approval. An admin
can add more categories to that list under Settings.

## Repository layout

`main` is a monorepo: it carries both the backend and the frontend, so one checkout runs
the whole application.

```
main
├── backend/            FastAPI service, database, tests
└── frontend/frontend/  React application
```

This was not always true. The backend and frontend were built and versioned separately, on
two branches with no shared git history. They were consolidated onto `main` in August 2026.
`master` is retained but archival, frozen at the tag `archive/master-final`; do not start
new work there.

### Directory tree

```
/
├── README.md                      this file
├── rag_knowledge.md               retrieval and question-answering design notes
├── Organization Profile Review/   the clinic's own documents (identity, policies and FAQ,
│                                  routing rules, staff directory), ingested for replies
├── .github/workflows/
│   ├── backend-ci.yml             backend lint, type check, and test pipeline
│   └── frontend-ci.yml            frontend lint and type-checked build
├── frontend/frontend/             Vite + React application, see "Frontend" below
│
└── backend/
    ├── README.md                  backend setup, tests, and the API endpoint table
    ├── Dockerfile                 Python 3.13 image, CPU-only torch
    ├── docker-compose.yml         development stack: api, db (Postgres + pgvector),
    │                              minio, ollama, adminer
    ├── docker-compose.prod.yml    deployment stack: caddy, api, db, minio
    ├── Caddyfile                  HTTPS, the built frontend, and the proxy to the API
    ├── .env.example               development settings template
    ├── .env.prod.example          deployment settings template
    ├── requirements.txt           dependency ranges used in development
    ├── requirements.lock          pinned versions, what the image and CI install
    ├── pyproject.toml             ruff and mypy configuration
    ├── alembic/versions/          database migrations, 0001 to 0041
    │
    ├── app/
    │   ├── main.py                FastAPI app, router registration, background jobs
    │   ├── config.py              all settings, read from the environment
    │   ├── database.py            async engine and session factory
    │   ├── limiter.py             login and public-form rate limiting
    │   ├── models/                SQLAlchemy tables
    │   ├── schemas/               Pydantic request and response models
    │   ├── routes/                API handlers, one file per area
    │   ├── services/              business logic behind the routes
    │   ├── auth/                  JWT, permissions, row-level scoping, and the route
    │   │                          registry the RBAC test suite reads
    │   ├── llm/                   provider.py (get_llm, Ollama or Bedrock), the input
    │   │                          guardrail and the output guardrail
    │   ├── rag/                   chunking, embeddings, hybrid retrieval, the sufficiency
    │   │                          gate, and grounded answer synthesis
    │   ├── agents/                the email agent: graph.py, nodes.py, state.py,
    │   │                          checkpointer.py
    │   └── storage/               MinIO object storage
    │
    ├── tests/                     the pytest suite, including test_rbac_enforcement.py
    │                              (every route against every role) and
    │                              test_audit_trigger.py (the audit log is append-only
    │                              against real Postgres)
    │
    ├── scripts/
    │   ├── run_tests_clean.sh     the suite against a throwaway database
    │   ├── create_admin.py        makes the first admin account
    │   ├── deploy.sh              deploys a release tag on the deployment host
    │   ├── seed_demo_patients.py, ingest_corpus_documents.py,
    │   │   ingest_appointment_history.py, assign_missing_doctors.py,
    │   │   ingest_org_profile.py, seed_demo_appointments.py     demo data
    │   └── outlook_login.py       one-time sign-in for the clinic mailbox
    │
    ├── ingestion/matthew_corpus/  100 synthetic patient folders used for the demo data
    └── Dataset Generator Code/    the script that produced that corpus
```

## Frontend

The frontend lives at `frontend/frontend/`, a Vite + React + TypeScript single-page app.
It talks to the backend over the REST API listed in `backend/README.md`. It is built for
desktop screens.

### Running it

```bash
cd frontend/frontend
cp .env.example .env      # VITE_API_BASE_URL=http://localhost:8000
npm install
npm run dev                # http://localhost:5173
```

`npm run build` type-checks with `tsc -b` (TypeScript strict) and then runs `vite build`,
emitting a production bundle to `dist/`. `npm run lint` runs ESLint over the project.

### Screens

All routes are defined in `src/App.tsx`.

**Without signing in:** Login, Forgot password, Reset password, and the patient
registration form a patient opens from an emailed link (`/register/<token>`).

**Signed in:** Dashboard, Patients (list, onboarding, detail, edit), Case, Contact,
Consent (queue, new, capture, view), Records (retrieval-based Q&A), Inbox, Review queue,
Add case, Escalations, Calendar and appointments (new, detail, edit), and Settings.
Settings includes the clinic mailbox sign-in and an Operations section showing the health
of the database, object storage, LLM provider and mailbox.

**Restricted:** Users is admin only. Audit log and Audit event detail need the
`read_audit` permission. Escalations is not available to doctors. The sidebar hides
whatever the signed-in user cannot open.

`frontend/frontend/README.md` documents the adapter seam in `src/api/`: components use
domain types only, so wiring a new backend field means changing an adapter, not a page.

## Tech stack

**Backend:** Python 3.13, FastAPI, async SQLAlchemy, Alembic, PostgreSQL with pgvector,
MinIO for object storage, JWT authentication, LangGraph for the email agent.

**Models:** LLM calls go through one provider switch (`LLM_PROVIDER`): Ollama for local
development, and Amazon Bedrock for deployment, using the Australian Haiku 4.5 inference
profile (`au.anthropic.claude-haiku-4-5-20251001-v1:0`) by default. Embeddings
(`nomic-embed-text`) and speech-to-text (Whisper) run inside the API process, not on
Bedrock.

**Frontend:** React, TypeScript, Vite, Tailwind CSS, React Router.

**Deployment:** Docker Compose and Caddy.

**Testing and CI:** pytest, ruff, mypy, GitHub Actions.

The development compose file also starts Adminer, for browsing the database.

## Getting started

### Prerequisites

- Docker and Docker Compose
- Git
- Node.js 22 (see `frontend/frontend/.nvmrc`), for the frontend
- Python 3.13, only needed if you want to run the backend outside Docker

### Backend

```bash
cd backend
cp .env.example .env
```

Open `.env` and set `JWT_SECRET_KEY` to a real generated value. Do not leave the
placeholder in place.

```bash
python -c "import secrets; print(secrets.token_urlsafe())"
```

Build the image, create the database tables, then start everything. The tables must
exist before the API starts, since it reads its settings table on startup:

```bash
docker compose build
docker compose run --rm api alembic upgrade head
docker compose up
```

The API is now running at `http://localhost:8000`. Interactive API docs are at
`http://localhost:8000/docs`.

Pull the local LLM model once, so classification and question answering have something
to call. The name must match `LLM_MODEL` in your `.env`:

```bash
docker compose exec ollama ollama pull gemma2:2b
```

Full backend setup, including running without Docker and the complete API endpoint
table, is documented in [backend/README.md](backend/README.md).

### Frontend

Keep the backend running in one terminal and the frontend dev server in a second (see
"Frontend" above for the commands), since the frontend needs the API to already be up.

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

The frontend has a login page but no sign-up page, and `POST /api/v1/auth/register`
needs a logged-in admin. The very first admin is made from a shell:

```bash
docker compose exec api python -m scripts.create_admin you@example.com "Your Name"
```

It asks for a password (at least 8 characters). Run against an existing account, it
keeps that account's password and makes it an active admin. Then log in on the frontend's
login page, and create everyone else from the Users page.

## Deployment

The deployment stack runs the whole application on one Linux host behind HTTPS. It is
meant for demonstrations on synthetic data, so it runs with `APP_ENV=staging`.

| File | What it is |
|---|---|
| `backend/docker-compose.prod.yml` | Four containers: `caddy`, `api`, `db`, `minio`. Only Caddy publishes ports (80 and 443) |
| `backend/Caddyfile` | Gets a certificate for `SITE_ADDRESS`, serves the built frontend, and proxies `/api/*`, `/health` and `/docs` to the API |
| `backend/.env.prod.example` | The settings template, with Bedrock as the LLM provider |
| `backend/scripts/deploy.sh` | Validates `.env`, checks out a release tag, rebuilds the image when its dependencies changed, migrates, restarts, and waits for the API to be healthy |
| `backend/scripts/create_admin.py` | Makes the first admin account |

On the host, with Docker, Docker Compose 2.20 or later and a clone of this repository:

```bash
cd backend
cp .env.prod.example .env      # fill SITE_ADDRESS, CORS_ORIGINS and the three secrets
scripts/deploy.sh --check      # refuses a missing or short secret, an unknown key,
                               # or a CORS_ORIGINS that does not start with the site
```

Build the frontend against the public address and put the result at
`frontend/frontend/dist` on the host. `deploy.sh` refuses to run without it:

```bash
cd frontend/frontend
npm ci
VITE_API_BASE_URL=https://<SITE_ADDRESS> npm run build
```

Then deploy a release tag and make the first admin:

```bash
cd backend
scripts/deploy.sh <release-tag>
docker compose -f docker-compose.prod.yml exec api python -m scripts.create_admin you@example.com "Your Name"
```

To load the demo data, run these inside the `api` container in this order:
`scripts.seed_demo_patients`, `scripts.ingest_corpus_documents`,
`scripts.ingest_appointment_history`, `scripts.assign_missing_doctors --apply`,
`scripts.ingest_org_profile`, `scripts.seed_demo_appointments`.

Things to know before running it:

- **Bedrock credentials.** On AWS the instance role supplies them. Elsewhere, set
  `AWS_BEARER_TOKEN_BEDROCK` in `.env`. The account must have access to the model in
  `BEDROCK_MODEL_ID`. Settings, Operations shows whether the model answers.
- **One API container only.** The mailbox poller, reminders and clean-up jobs run inside
  the API process, so a second copy would send every email twice. For the same reason,
  only one running stack may have `OUTLOOK_ENABLED=true` for a given mailbox.
- **Links in emails** (registration form, password reset) are built from the first entry
  in `CORS_ORIGINS`, which is why it must be the public address.
- **A later release** is a new tag and `scripts/deploy.sh <new-tag>` again. A frontend
  change is a rebuild and a copy of `dist/`; nothing restarts.

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
scripts/run_tests_clean.sh
```

The script creates a throwaway database, migrates it, runs the suite and drops it, which
is what CI does. Do not point the suite at the development database: rows left by earlier
runs make correct tests fail. `backend/README.md` explains why, and which tests need real
Postgres, MinIO or Ollama.

Lint and type checks, all required in CI:

```bash
ruff check app tests
ruff format --check app tests
mypy app
```

## Documentation

- [backend/README.md](backend/README.md): backend setup, tests, environment variables,
  and the complete API endpoint table.
- [frontend/frontend/README.md](frontend/frontend/README.md): frontend structure.
- `rag_knowledge.md`: how the retrieval and question answering pipeline works, and where
  its data comes from.
- `backend/docs/retrieval_contract.md`: what the retrieval layer promises its callers.
- `backend/scripts/intent_classifier/RESULTS.md`: the measurements behind the classifier
  and the intent check.
- `backend/app/auth/permissions.py`: the role-to-permission map, the source of truth for
  which role can do what.

## Known limitations

- A red-flag symptom always escalates, even when the sentence negates it ("no chest
  pain"). This is a deliberate fail-safe choice: it over-escalates rather than risks
  missing something urgent.
- Email and call classification into a category uses a confidence threshold. Anything
  below it goes to the Review Queue instead of being routed automatically.
- Embeddings always run locally with `nomic-embed-text`. `EMBEDDING_PROVIDER=bedrock` is
  not implemented.
- This system is for administrative record keeping. It gives no diagnosis or treatment
  advice.
