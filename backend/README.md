# VitalAI Backend

FastAPI backend for the VitalAI clinic administration platform: patients, intake and
consent, cases, triage and routing, the email, call and voicemail pipeline, the email
agent, appointments, clinical document upload, and retrieval-based Q&A over stored
records.

Built on async SQLAlchemy with Postgres and pgvector, JWT auth with permission-based
access control (`app/auth/permissions.py`), an append-only audit log enforced at the
database level, and an LLM provider switch that lets Ollama (development) and Amazon
Bedrock (deployment) be swapped through configuration.

The root [README](../README.md) describes what the system does and how to deploy it.
This file covers running, testing and the API.

## Quick start (Docker Compose, recommended)

```bash
cd backend
cp .env.example .env
```

Generate a real secret and put it in `.env` as `JWT_SECRET_KEY`. Never leave the
placeholder value in place once you have a real one.

```bash
python -c "import secrets; print(secrets.token_urlsafe())"
```

Create the tables before the API starts, since it reads its settings table on startup:

```bash
docker compose build
docker compose run --rm api alembic upgrade head
docker compose up
```

API runs at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

Pull the dev model into Ollama once. The name must match `LLM_MODEL` in `.env`
(`.env.example` sets `gemma2:2b`):

```bash
docker compose exec ollama ollama pull gemma2:2b
```

Make the first admin account, then create everyone else from the Users page:

```bash
docker compose exec api python -m scripts.create_admin you@example.com "Your Name"
```

## Quick start (local, no Docker)

Needs Python 3.13 (the version both `ruff` and `mypy` target in `pyproject.toml`) and
a running Postgres instance with pgvector. The project has also been run successfully on
3.14 in local development, but 3.13 is the only version actually declared in the repo.

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
```

Set `JWT_SECRET_KEY` (generate one as shown above) and point `DATABASE_URL` at your
local Postgres in `.env`. Then:

```bash
alembic upgrade head
uvicorn app.main:app --reload
```

The Docker image and CI install from the pinned lock file instead, so builds are
reproducible:

```bash
pip install -r requirements.lock
```

To regenerate the lock file after changing `requirements.txt`:

```bash
pip install pip-tools
pip-compile requirements.txt --output-file requirements.lock
```

## Deployment

`docker-compose.prod.yml`, `Caddyfile`, `.env.prod.example` and `scripts/deploy.sh` run
the application on one host behind HTTPS. The steps are in the root
[README](../README.md#deployment). Two details that matter when changing this service:

- The repository is bind-mounted into the `api` container, so a code change needs only a
  restart. `deploy.sh` rebuilds the image only when `Dockerfile`, `.dockerignore`,
  `requirements.txt` or `requirements.lock` changed.
- `deploy.sh --check` refuses any key in `.env` that `app/config.py` does not define. A
  new setting therefore needs its field in `Settings` before it can be set on the host.

## Running tests

### The clean run (use this one)

```bash
scripts/run_tests_clean.sh              # whole suite
scripts/run_tests_clean.sh tests/test_audit_verify.py -x
```

This creates a throwaway database, runs `alembic upgrade head` against virgin
schema, runs the suite, and drops the database afterwards. It is what CI does,
and it is the only invocation whose failures all mean something.

Pointing `DATABASE_URL` at the shared dev database (`vitalai`) instead produces
around seventeen failures that have nothing to do with your change. That
database carries committed rows from every earlier run:

- `app_settings`, `appointments` and `human_review_tasks` rows, which break
  tests that assert on a count or an exact list.
- An `audit_events` hash chain that is already broken, so `verify_audit_chain()`
  reports `valid = false` before any test runs. `audit_events` is append-only and
  undeletable by design, which is the point of it, so that chain can never be
  repaired in place. Every chain-verification test fails there permanently.

Tests that could be scoped to their own fixtures have been. The rest are correct
tests that need a database nobody has used yet, which is what the script gives
them. Do not "fix" them by wiping the dev database: it holds demo data, and
other worktrees point at the same Postgres instance.

The script sets `RAG_TEST_DATABASE_URL` and `POSTGRES_TEST_URL` alongside
`DATABASE_URL`. Exporting only `DATABASE_URL` by hand is not enough, because
conftest's `pg_session`/`seeded_chunks` fixtures and `test_audit_hash_chain.py`
read those other two and fall back to the shared dev database.

One more trap: if another branch has migrated the dev database to a revision
your branch does not have (`Can't locate revision identified by ...`), every
Postgres test errors at fixture setup rather than failing. The scratch database
is immune, since it is migrated from scratch by your own tree.

### What still needs real infrastructure

Run with no `DATABASE_URL` set, the suite uses SQLite and needs no setup, but
that is a partial run. Some tests need real infrastructure and are not skipped
automatically if it's missing: anything touching `app.rag.retrieval`/the
`chunks` table needs real Postgres+pgvector (the
`pg_session`/`seeded_chunks`/`pg_client` fixtures), several calendar tests in
`test_clinic_timezone.py` fail on SQLite, the clinical document upload tests
(`test_object_storage.py`, plus the upload-success paths in
`test_clinical_documents.py`/`test_clinical_document_service.py`) need a real
MinIO instance, and anything that classifies or summarizes text through the LLM
switch (`test_inbox.py`, `test_content_classifier.py`, `test_rag_answer.py`,
`test_email_routes.py`, and others that route through `get_llm()`) needs a real
Ollama instance with the dev model pulled:

```bash
docker compose up -d db minio ollama
docker exec $(docker compose ps -q ollama) ollama pull gemma2:2b   # once; persists in the ollama_data volume
OLLAMA_BASE_URL=http://localhost:11434 pytest
```

Without `db`/`minio`/`ollama` running, the affected tests fail with connection
errors (or, for `ollama`, a DNS/connection-refused error resolving the
docker-internal `ollama` hostname from the host) rather than skipping.

No test can reach Bedrock: `tests/conftest.py` refuses any call to a `bedrock*`
service.

Three tests prove the audit log's append-only guarantee and need a real Postgres
instance, since SQLite does not enforce the database trigger they're checking. The
Postgres service in `docker-compose.yml` is named `db`, not `postgres`:

```bash
docker compose up -d db
export DATABASE_URL="postgresql+asyncpg://vitalai:vitalai@localhost:5432/vitalai"
export POSTGRES_TEST_URL="postgresql+asyncpg://vitalai:vitalai@localhost:5432/vitalai"
pytest tests/test_audit_trigger.py -v
```

`DATABASE_URL` has to be set too, not just `POSTGRES_TEST_URL`: conftest.py's
`test_engine` fixture reads `DATABASE_URL` and defaults to SQLite when it is
unset, and the Postgres-only fixtures in this file skip whenever the engine
dialect isn't `postgresql`, regardless of `POSTGRES_TEST_URL`.

Without both set, those three tests skip rather than fail. A skip is not
a pass: if you're verifying the audit guarantee, confirm they actually ran.

Coverage:

```bash
pytest --cov=app --cov-report=term-missing
```

Lint and type checks, all required to pass in CI:

```bash
ruff check app tests
ruff format --check app tests
mypy app
```

## Repository layout

```
backend/
├── docker-compose.yml         development stack: api, db, minio, ollama, adminer
├── docker-compose.prod.yml    deployment stack: caddy, api, db, minio
├── Caddyfile                  HTTPS, the built frontend, and the proxy to the API
├── Dockerfile                 Python 3.13 image, CPU-only torch
├── requirements.txt           dependency ranges
├── requirements.lock          pinned versions, what the image and CI install
├── .env.example               development settings template
├── .env.prod.example          deployment settings template
├── alembic/versions/          migrations, 0001 to 0041
├── app/
│   ├── main.py                FastAPI app, router registration, background jobs
│   ├── config.py              every setting, read from the environment
│   ├── database.py            async engine and session factory
│   ├── limiter.py             login and public-form rate limiting
│   ├── models/                SQLAlchemy tables
│   ├── schemas/               Pydantic request and response contracts
│   ├── auth/                  JWT, permissions, row-level scoping, the route registry
│   ├── routes/                API handlers, one file per area
│   ├── services/              business logic
│   ├── llm/                   get_llm() and the input and output guardrails
│   ├── rag/                   chunking, embeddings, hybrid retrieval, gating, answers
│   ├── agents/                the email agent (LangGraph): graph, nodes, state,
│   │                          checkpointer
│   └── storage/               MinIO object storage
├── scripts/                   create_admin, deploy.sh, run_tests_clean.sh, demo data
│                              seeding and ingestion, outlook_login
├── tests/                     the pytest suite
└── docs/                      retrieval_contract.md
```

The background jobs started in `main.py` all run inside the API process: the Outlook
mailbox poller (`OUTLOOK_ENABLED`), appointment reminders
(`APPOINTMENT_REMINDERS_ENABLED`), the provisional-patient purge
(`AGENTIC_PIPELINE_ENABLED`), the voicemail audio sweep and the case-close nudges. Run
exactly one API process against a database, or outbound email is duplicated.

## API endpoints

Everything under `/api/v1/*` needs a JWT unless the table says Public. Registration needs
an admin and always creates a `front_desk` user regardless of the `role` field in the
request body. Use the elevate endpoint to promote a user. The first admin on a fresh
database comes from `python -m scripts.create_admin <email> "<name>"`.

The tables below list every route the application serves and the check FastAPI runs
before the handler. They were generated from the same registry the RBAC test suite reads
(`app/auth/rbac_registry.py`). `http://localhost:8000/docs` has the request and response
shapes. The `/api/v1/voice/*` routes exist only when `TWILIO_ENABLED=true`.

**Health**

| Method | Path | Access |
|---|---|---|
| GET | `/` | Public |
| GET | `/api/v1/health/detailed` | `READ_AUDIT` |
| GET | `/health` | Public |

**Accounts and users**

| Method | Path | Access |
|---|---|---|
| POST | `/api/v1/auth/login` | Public |
| GET | `/api/v1/auth/me` | Any signed-in user |
| POST | `/api/v1/auth/me/password` | Any signed-in user |
| POST | `/api/v1/auth/password-reset/confirm` | Public |
| POST | `/api/v1/auth/password-reset/request` | Public |
| POST | `/api/v1/auth/register` | `MANAGE_USERS` |
| GET | `/api/v1/auth/users` | `MANAGE_USERS` |
| POST | `/api/v1/auth/users/{user_id}/active` | `MANAGE_USERS` |
| POST | `/api/v1/auth/users/{user_id}/department` | `MANAGE_USERS` |
| POST | `/api/v1/auth/users/{user_id}/elevate` | `MANAGE_USERS` |
| GET | `/api/v1/auth/users/{user_id}/grants` | `MANAGE_USERS` |
| POST | `/api/v1/auth/users/{user_id}/grants` | `MANAGE_USERS` |
| DELETE | `/api/v1/auth/users/{user_id}/grants/{permission}` | `MANAGE_USERS` |

**Patients and assignments**

| Method | Path | Access |
|---|---|---|
| GET | `/api/v1/assignments` | `ASSIGN_PATIENTS` |
| POST | `/api/v1/assignments` | `ASSIGN_PATIENTS` |
| DELETE | `/api/v1/assignments/{doctor_id}/{patient_id}` | `ASSIGN_PATIENTS` |
| GET | `/api/v1/doctors` | `MANAGE_APPOINTMENTS_ALL` or `MANAGE_OWN_CALENDAR` |
| GET | `/api/v1/patients` | `VIEW_RECORDS_GENERAL` |
| POST | `/api/v1/patients` | `REGISTER_PATIENT` |
| GET | `/api/v1/patients/{patient_id}` | `VIEW_RECORDS_GENERAL` |
| PATCH | `/api/v1/patients/{patient_id}` | `REGISTER_PATIENT` |
| PUT | `/api/v1/patients/{patient_id}/doctor` | `ASSIGN_PATIENTS` |
| POST | `/api/v1/patients/{patient_id}/promote` | `REGISTER_PATIENT` |
| GET | `/api/v1/public/registration/{token}` | Public, rate limited |
| POST | `/api/v1/public/registration/{token}` | Public, rate limited |

**Intake, consent, triage and routing**

| Method | Path | Access |
|---|---|---|
| GET | `/api/v1/consent` | `VIEW_RECORDS_GENERAL` |
| POST | `/api/v1/consent` | `CAPTURE_CONSENT` |
| GET | `/api/v1/consent/by-case/{case_id}` | `VIEW_RECORDS_GENERAL` |
| GET | `/api/v1/consent/queue` | `CAPTURE_CONSENT` |
| POST | `/api/v1/consent/{consent_id}/capture` | `CAPTURE_CONSENT` |
| POST | `/api/v1/consent/{consent_id}/resolve-review` | `CAPTURE_CONSENT` |
| POST | `/api/v1/consent/{consent_id}/verify` | `CAPTURE_CONSENT` |
| POST | `/api/v1/consent/{consent_id}/withdraw` | `CAPTURE_CONSENT` |
| GET | `/api/v1/intake` | `VIEW_QUEUE` |
| POST | `/api/v1/intake` | `VIEW_QUEUE` |
| GET | `/api/v1/intake/{case_id}` | `VIEW_QUEUE` |
| PATCH | `/api/v1/intake/{case_id}/status` | `MANAGE_CASES` |
| POST | `/api/v1/routing` | `MANAGE_CASES` |
| GET | `/api/v1/routing/by-case/{case_id}` | `VIEW_QUEUE` |
| POST | `/api/v1/triage` | `MANAGE_CASES` |

**Cases**

| Method | Path | Access |
|---|---|---|
| GET | `/api/v1/cases` | `VIEW_RECORDS_GENERAL` |
| POST | `/api/v1/cases` | `REGISTER_PATIENT` or `VIEW_CLINICAL` |
| POST | `/api/v1/cases/move` | `REGISTER_PATIENT` or `VIEW_CLINICAL` |
| GET | `/api/v1/cases/{episode_id}` | `VIEW_RECORDS_GENERAL` |
| PATCH | `/api/v1/cases/{episode_id}` | `REGISTER_PATIENT` or `VIEW_CLINICAL` |
| POST | `/api/v1/cases/{episode_id}/close` | `REGISTER_PATIENT` or `VIEW_CLINICAL` |
| POST | `/api/v1/cases/{episode_id}/contact` | `REGISTER_PATIENT` or `VIEW_CLINICAL` |
| POST | `/api/v1/cases/{episode_id}/reopen` | `REGISTER_PATIENT` or `VIEW_CLINICAL` |

**Appointments**

| Method | Path | Access |
|---|---|---|
| GET | `/api/v1/appointments` | `MANAGE_APPOINTMENTS_ALL` or `MANAGE_OWN_CALENDAR` |
| POST | `/api/v1/appointments` | `MANAGE_APPOINTMENTS_ALL` or `MANAGE_OWN_CALENDAR` |
| GET | `/api/v1/appointments/availability` | `MANAGE_APPOINTMENTS_ALL` or `MANAGE_OWN_CALENDAR` |
| GET | `/api/v1/appointments/calendar` | `MANAGE_APPOINTMENTS_ALL` or `MANAGE_OWN_CALENDAR` |
| GET | `/api/v1/appointments/calendar/markers` | `MANAGE_APPOINTMENTS_ALL` or `MANAGE_OWN_CALENDAR` |
| GET | `/api/v1/appointments/day` | `MANAGE_APPOINTMENTS_ALL` or `MANAGE_OWN_CALENDAR` |
| POST | `/api/v1/appointments/suggest` | `MANAGE_APPOINTMENTS_ALL` or `MANAGE_OWN_CALENDAR` |
| GET | `/api/v1/appointments/{appointment_id}` | `MANAGE_APPOINTMENTS_ALL` or `MANAGE_OWN_CALENDAR` |
| PATCH | `/api/v1/appointments/{appointment_id}` | `MANAGE_APPOINTMENTS_ALL` or `MANAGE_OWN_CALENDAR` |
| POST | `/api/v1/appointments/{appointment_id}/cancel` | `MANAGE_APPOINTMENTS_ALL` or `MANAGE_OWN_CALENDAR` |
| POST | `/api/v1/appointments/{appointment_id}/complete` | `MANAGE_APPOINTMENTS_ALL` or `MANAGE_OWN_CALENDAR` |
| POST | `/api/v1/appointments/{appointment_id}/reschedule` | `MANAGE_APPOINTMENTS_ALL` or `MANAGE_OWN_CALENDAR` |

**Email, inbox and tasks**

| Method | Path | Access |
|---|---|---|
| GET | `/api/v1/approvals` | `MANAGE_CASES` |
| POST | `/api/v1/approvals/{approval_id}/approve` | `APPROVE_ACTION` |
| POST | `/api/v1/approvals/{approval_id}/reject` | `APPROVE_ACTION` |
| POST | `/api/v1/email/ingest` | `VIEW_QUEUE` |
| GET | `/api/v1/inbox` | `VIEW_CLINICAL` or `VIEW_QUEUE` |
| GET | `/api/v1/inbox/{task_id}` | `VIEW_CLINICAL` or `VIEW_QUEUE` |
| POST | `/api/v1/inbox/{task_id}/reply` | `VIEW_CLINICAL` or `VIEW_QUEUE` |
| GET | `/api/v1/tasks` | `VIEW_QUEUE` |
| POST | `/api/v1/tasks` | `MANAGE_CASES` |
| DELETE | `/api/v1/tasks/{task_id}` | `DELETE_MESSAGES` |
| GET | `/api/v1/tasks/{task_id}` | `VIEW_QUEUE` |
| PATCH | `/api/v1/tasks/{task_id}` | `MANAGE_CASES` |
| POST | `/api/v1/tasks/{task_id}/archive` | `VIEW_CLINICAL` or `VIEW_QUEUE` |
| GET | `/api/v1/tasks/{task_id}/comments` | `VIEW_QUEUE` |
| POST | `/api/v1/tasks/{task_id}/comments` | `VIEW_QUEUE` |
| POST | `/api/v1/tasks/{task_id}/escalate` | `VIEW_CLINICAL` or `VIEW_QUEUE` |
| POST | `/api/v1/tasks/{task_id}/override` | `MANAGE_CASES` |
| POST | `/api/v1/tasks/{task_id}/read` | `VIEW_CLINICAL` or `VIEW_QUEUE` |

**Review Queue**

| Method | Path | Access |
|---|---|---|
| GET | `/api/v1/human-review` | `VIEW_CLINICAL` or `VIEW_QUEUE` |
| POST | `/api/v1/human-review` | `VIEW_CLINICAL` or `VIEW_QUEUE` |
| GET | `/api/v1/human-review/stats/daily` | `VIEW_CLINICAL` or `VIEW_QUEUE` |
| POST | `/api/v1/human-review/{task_id}/case-close` | `VIEW_CLINICAL` or `VIEW_QUEUE` |
| POST | `/api/v1/human-review/{task_id}/choose-case` | `VIEW_CLINICAL` or `VIEW_QUEUE` |
| POST | `/api/v1/human-review/{task_id}/claim` | `VIEW_CLINICAL` or `VIEW_QUEUE` |
| POST | `/api/v1/human-review/{task_id}/complete` | `VIEW_CLINICAL` or `VIEW_QUEUE` |
| POST | `/api/v1/human-review/{task_id}/escalate` | `VIEW_CLINICAL` or `VIEW_QUEUE` |
| POST | `/api/v1/human-review/{task_id}/link-patient` | `VIEW_CLINICAL` or `VIEW_QUEUE` |
| POST | `/api/v1/human-review/{task_id}/reassign` | `VIEW_CLINICAL` or `VIEW_QUEUE` |
| POST | `/api/v1/human-review/{task_id}/reject` | `VIEW_CLINICAL` or `VIEW_QUEUE` |
| POST | `/api/v1/human-review/{task_id}/reroute` | `VIEW_CLINICAL` or `VIEW_QUEUE` |

**Calls and voicemail**

| Method | Path | Access |
|---|---|---|
| GET | `/api/v1/calls` | `VIEW_QUEUE` |
| POST | `/api/v1/calls` | `VIEW_QUEUE` |
| POST | `/api/v1/calls/transcribe` | `VIEW_QUEUE` |
| GET | `/api/v1/calls/{call_id}` | `VIEW_QUEUE` |
| GET | `/api/v1/calls/{call_id}/audio` | `PLAY_VOICEMAIL` |
| POST | `/api/v1/calls/{call_id}/escalate` | `MANAGE_CASES` |
| POST | `/api/v1/calls/{call_id}/override-routing` | `MANAGE_CASES` |
| POST | `/api/v1/calls/{call_id}/route` | `MANAGE_CASES` |
| POST | `/api/v1/voice/done` | Public, Twilio signature checked |
| POST | `/api/v1/voice/gather/{step}` | Public, Twilio signature checked |
| POST | `/api/v1/voice/incoming` | Public, Twilio signature checked |
| POST | `/api/v1/voice/recording` | Public, Twilio signature checked |
| POST | `/api/v1/voice/status` | Public, Twilio signature checked |
| POST | `/api/v1/voicemails/simulate` | `MANAGE_CASES` |

**Clinical documents and retrieval**

| Method | Path | Access |
|---|---|---|
| GET | `/api/v1/clinical-documents` | `UPLOAD_CLINICAL` or `VIEW_CLINICAL` |
| POST | `/api/v1/clinical-documents` | `UPLOAD_CLINICAL` |
| GET | `/api/v1/clinical-documents/{document_id}/file` | `VIEW_CLINICAL` |
| POST | `/api/v1/clinical-documents/{document_id}/ingest` | `UPLOAD_CLINICAL` |
| GET | `/api/v1/rag/documents` | `VIEW_CLINICAL` |
| POST | `/api/v1/rag/query` | `VIEW_CLINICAL` |

**Audit**

| Method | Path | Access |
|---|---|---|
| GET | `/api/v1/audit` | `READ_AUDIT` |
| GET | `/api/v1/audit/by-case/{case_id}` | `READ_AUDIT` |
| GET | `/api/v1/audit/incidents` | `READ_AUDIT` |
| GET | `/api/v1/audit/verify` | `READ_AUDIT` |
| GET | `/api/v1/audit/{event_id}` | `READ_AUDIT` |

**Settings, integrations and LLM**

| Method | Path | Access |
|---|---|---|
| GET | `/api/v1/integrations/outlook` | `CONFIGURE_GOVERNANCE` |
| GET | `/api/v1/integrations/outlook/callback` | Public, Microsoft redirects here |
| POST | `/api/v1/integrations/outlook/connect` | `CONFIGURE_GOVERNANCE` |
| POST | `/api/v1/llm/ping` | Role admin or operator |
| GET | `/api/v1/llm/status` | Role admin or operator |
| GET | `/api/v1/settings` | `CONFIGURE_GOVERNANCE` |
| PATCH | `/api/v1/settings` | `CONFIGURE_GOVERNANCE` |

A named permission is checked with `require_permission()` or `require_any_permission()`
(`app/auth/permissions.py`, `app/auth/dependencies.py`), not against a role directly.
`permissions.py` holds the role-to-permission map, and an admin can grant a single
permission to a single user. Doctors are additionally scoped to their own assigned
patients and their own calendar. `/api/v1/llm/*` is the one exception to the permission
model, kept on the older role-based `require_roles()` since it is operations diagnostics.

## Rate limiting

`POST /api/v1/auth/login` and the two password-reset routes are limited to 5 requests per
minute per client address using [slowapi](https://github.com/laurents/slowapi). Exceeding
the limit returns `429 Too Many Requests`.

The limit is configurable through `LOGIN_RATE_LIMIT` in `.env` (default `5/minute`).
Accepts any [limits](https://limits.readthedocs.io/en/stable/string-notation.html)
string, for example `10/minute` or `100/hour`. The public registration form has its own
limit, `PUBLIC_FORM_RATE_LIMIT` (default `10/minute`).

Behind a reverse proxy, uvicorn must be started with `--proxy-headers`, as
`docker-compose.prod.yml` does. Without it every visitor has the proxy's address and
they all share one limit.

## LLM provider switch

Set `LLM_PROVIDER` in `.env`:

- `ollama`: development. Uses `LLM_MODEL` through `OLLAMA_BASE_URL`. The code default is
  `gemma2:9b`; `.env.example` sets `gemma2:2b`.
- `bedrock`: deployment. Uses `BEDROCK_MODEL_ID` in `AWS_REGION`. The default is the
  Australian Haiku 4.5 inference profile, `au.anthropic.claude-haiku-4-5-20251001-v1:0`,
  in `ap-southeast-2`. Credentials come from the usual AWS chain (an instance role on
  EC2) or from `AWS_BEARER_TOKEN_BEDROCK`.

`app/llm/provider.py` is where the LLM client itself gets constructed: `get_llm()`
switches between Ollama and Bedrock based on `LLM_PROVIDER`, and nothing else builds an
LLM client directly. Bedrock is called through the Converse API and piped through a
string parser, so `ainvoke()` returns plain text for both providers. `LLM_TEMPERATURE`,
`LLM_MAX_TOKENS` and `LLM_TIMEOUT_SECONDS` apply to both.

`GET /api/v1/health/detailed` (Settings, Operations in the frontend) reports the
provider's status. With Bedrock it makes a one-token call each time, which proves the
credentials, the model access and the model id together.

Embeddings do not go through this switch. `app/rag/embeddings.py` always runs
`nomic-embed-text` locally with sentence-transformers; `EMBEDDING_PROVIDER=bedrock` is
not implemented. The model downloads on first use (about 500 MB).

## Append-only audit log

The `audit_events` table has database-level triggers that reject `UPDATE` and `DELETE`.
Any attempt to modify a row fails at the database. This is what backs the tamper-evident
claim in the design documentation. It is plain Postgres trigger enforcement, not a
blockchain or distributed ledger. A hash chain over the events is checked by
`GET /api/v1/audit/verify`.

`tests/test_audit_trigger.py` is the source of truth for this guarantee, since it runs
against real Postgres and proves the trigger fires. See Running tests above for how to
run it. If a migration touching `audit_events` is ever rewritten, that test is what
confirms the guarantee still holds, not this README.

## Known limitations

A red-flag symptom always counts as urgent, even when the sentence negates it ("no chest
pain"). General urgency words are skipped when negated; red flags never are
(`triage_service.is_urgent`). This fails safe: it over-escalates rather than misses
something urgent. Do not relax it without adding tests for the cases that would then be
missed.

`ConsentStatus.NOT_REQUIRED` is defined in the enum but nothing in the codebase sets a
record to that status. Before anything does, the consent guard in triage needs an
explicit branch and a test.

## Constraints

This system does not provide clinical decision support, diagnosis, or treatment
recommendations. It is administrative only.

This boundary covers any clinician-facing record access too: where it exists, it
retrieves and displays records as they are. It does not interpret, summarize
clinically, or score them. Clinical judgment stays with the clinician.

Every state-changing operation writes to the audit log with the authenticated actor.

## Security notes

`.env` is gitignored and must never be committed. `.env.example` and `.env.prod.example`
should only ever contain placeholder values. If you generate a real secret, it goes in
`.env` and nowhere else.

`.outlook_token_cache.json` holds a live refresh token for the clinic mailbox. It is
gitignored too.

## Twilio voicemail line

Off by default (`TWILIO_ENABLED=false`); the `/api/v1/voice/*` routes are not mounted then.
The simulated path (`POST /api/v1/voicemails/simulate`) runs the same pipeline without
Twilio.

1. Buy an Australian number in the Twilio console.
2. Voice settings: turn on **Enforce HTTP Auth on Media URLs**, so a recording cannot be
   fetched by anyone holding its link before we delete it.
3. Expose the API: `ngrok http 8000`, and set `TWILIO_WEBHOOK_BASE_URL` to the https origin.
4. On the number: "A call comes in" -> Webhook, POST, `<base>/api/v1/voice/incoming`;
   "Call status changes" -> POST, `<base>/api/v1/voice/status`.
5. `.env`: `TWILIO_ENABLED=true`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WEBHOOK_BASE_URL`.

Recordings are downloaded, stored in MinIO, then deleted from Twilio. Twilio's own
request logs still hold the keypad digits and caller number for its log retention period.
