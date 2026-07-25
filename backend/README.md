# VitalAI Backend

FastAPI backend for administrative intake, consent, triage, routing, patients,
appointments, clinical document upload/retrieval, and RAG-based clinical Q&A.

Built on async SQLAlchemy with Postgres, JWT auth with permission-based access control
(`app/auth/permissions.py`, per `VitalAI RBAC Report - Audit Trail.md`), an append-only
audit log enforced at the database level, and an LLM provider abstraction that lets
Ollama (dev) and Bedrock (prod) be swapped through configuration.

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

```bash
docker compose up --build
docker compose exec api alembic upgrade head
```

API runs at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

Pull the dev model into Ollama once:

```bash
docker compose exec ollama ollama pull gemma2:9b
```

## Quick start (local, no Docker)

Needs Python 3.13 (the version both `ruff` and `mypy` target in `pyproject.toml`) and
a running Postgres instance. The project has also been run successfully on 3.14 in
local development, but 3.13 is the only version actually declared in the repo.

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

For deployment, use the pinned lock file instead of `requirements.txt` so builds are
reproducible:

```bash
pip install -r requirements.lock
```

To regenerate the lock file after changing `requirements.txt`:

```bash
pip install pip-tools
pip-compile requirements.txt --output-file requirements.lock
```

## Running tests

Most of the suite runs against SQLite and needs no setup. Some tests need real
infrastructure and are not skipped automatically if it's missing: anything
touching `app.rag.retrieval`/the `chunks` table needs real Postgres+pgvector
(the `pg_session`/`seeded_chunks`/`pg_client` fixtures), and the clinical
document upload tests (`test_object_storage.py`, plus the upload-success paths
in `test_clinical_documents.py`/`test_clinical_document_service.py`) need a
real MinIO instance:

```bash
docker compose up -d db minio
pytest
```

Without `db`/`minio` running, the affected tests fail with connection errors
rather than skipping.

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

Lint and type checks, both required to pass in CI:

```bash
ruff check app tests
mypy app
```

## Repository layout

```
/                                  monorepo root
├── .github/workflows/             CI pipelines
├── backend/                       this service
│   ├── docker-compose.yml         FastAPI + Postgres + Redis + MinIO + Ollama
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── requirements.lock
│   ├── alembic.ini
│   ├── .env.example
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/               13 migrations: initial schema and the
│   │                                append-only audit trigger (0001) through
│   │                                RBAC roles/grants (0008-0009), patients
│   │                                (0010), doctor-patient assignments (0011),
│   │                                clinical documents (0012), and the user
│   │                                department field (0013)
│   ├── permissions/                 contains only settings.local.json (tool config,
│   │                                not application permission logic; RBAC lives in
│   │                                app/auth/)
│   └── app/
│       ├── main.py                  FastAPI app and lifespan setup
│       ├── config.py                pydantic-settings, env-driven
│       ├── database.py              async engine and session factory
│       ├── models/                  SQLAlchemy ORM: users, case, consent, triage,
│       │                            routing, audit, human review
│       ├── schemas/                 Pydantic request and response contracts
│       ├── auth/                    JWT and RBAC: security, dependencies
│       ├── llm/                     provider abstraction, get_llm() switches by env
│       ├── rag/                     retrieval pipeline (Sprint 2, in progress)
│       ├── agents/                  pipeline agents (Sprint 2 onward, in progress)
│       ├── routes/                  API handlers: health, auth, intake, consent,
│       │                            triage, routing, audit, llm
│       └── services/                business logic
├── frontend/                       React app (in progress)
└── docs/                           planning docs and decision log
```

## API endpoints

Everything under `/api/v1/*` needs a JWT except `POST /api/v1/auth/register` and
`POST /api/v1/auth/login`. Registration always creates a `front_desk` user regardless of
the `role` field in the request body. Use the elevate endpoint to promote a user.

| Method | Path                                   | Auth | Permission (or Role)       | Description                       |
|--------|-----------------------------------------|------|------------------------------|------------------------------------|
| GET    | `/health`                               | No   | Public                       | Health check                       |
| POST   | `/api/v1/auth/register`                 | No   | Public                       | Register user, role forced to front_desk |
| POST   | `/api/v1/auth/login`                    | No   | Public                       | Get JWT, 5 requests/min per IP    |
| GET    | `/api/v1/auth/me`                       | Yes  | any                          | Current user                       |
| POST   | `/api/v1/auth/users/{user_id}/elevate`  | Yes  | MANAGE_USERS                 | Change a user's role, audited       |
| POST   | `/api/v1/auth/users/{user_id}/department` | Yes | MANAGE_USERS                | Set a user's department, audited    |
| GET    | `/api/v1/auth/users`                    | Yes  | MANAGE_USERS                 | List users, paginated, name/email search, derived `last_active` |
| POST   | `/api/v1/auth/users/{user_id}/grants`   | Yes  | MANAGE_USERS                 | Grant a permission to a user        |
| DELETE | `/api/v1/auth/users/{user_id}/grants/{permission}` | Yes | MANAGE_USERS      | Revoke a granted permission         |
| POST   | `/api/v1/intake`                        | Yes  | any                          | Create intake case                  |
| GET    | `/api/v1/intake/{id}`                   | Yes  | any                          | Get intake case                     |
| PATCH  | `/api/v1/intake/{id}/status`            | Yes  | MANAGE_CASES                 | Update intake status                |
| POST   | `/api/v1/consent`                       | Yes  | CAPTURE_CONSENT               | Create consent record               |
| GET    | `/api/v1/consent/by-case/{case_id}`     | Yes  | VIEW_RECORDS_GENERAL          | Get consent for case, doctor scoped to assigned patients |
| POST   | `/api/v1/consent/{id}/capture`          | Yes  | CAPTURE_CONSENT               | Capture consent (pending to captured) |
| POST   | `/api/v1/consent/{id}/withdraw`         | Yes  | CAPTURE_CONSENT               | Withdraw consent                    |
| POST   | `/api/v1/triage`                        | Yes  | MANAGE_CASES                  | Classify case urgency, blocked unless consent is captured |
| POST   | `/api/v1/routing`                       | Yes  | MANAGE_CASES                  | Create routing decision             |
| GET    | `/api/v1/routing/by-case/{case_id}`     | Yes  | VIEW_QUEUE                    | Get latest routing decision         |
| GET    | `/api/v1/audit/by-case/{case_id}`       | Yes  | READ_AUDIT                    | Get audit trail for case; the read itself is logged too |
| POST   | `/api/v1/patients`                      | Yes  | REGISTER_PATIENT              | Register a patient, server-generates MRN |
| GET    | `/api/v1/patients`                      | Yes  | VIEW_RECORDS_GENERAL          | List/search patients with status counts, doctor scoped to assigned patients |
| POST   | `/api/v1/assignments`                   | Yes  | ASSIGN_PATIENTS               | Assign a patient to a doctor        |
| DELETE | `/api/v1/assignments/{doctor_id}/{patient_id}` | Yes | ASSIGN_PATIENTS      | Unassign a patient from a doctor    |
| GET    | `/api/v1/assignments`                   | Yes  | ASSIGN_PATIENTS               | List a doctor's assigned patients   |
| POST   | `/api/v1/appointments`                  | Yes  | MANAGE_APPOINTMENTS_ALL or MANAGE_OWN_CALENDAR | Book an appointment, doctor restricted to own calendar |
| GET    | `/api/v1/appointments`                  | Yes  | MANAGE_APPOINTMENTS_ALL or MANAGE_OWN_CALENDAR | List appointments, doctor forced to own calendar |
| POST   | `/api/v1/appointments/{id}/reschedule`  | Yes  | MANAGE_APPOINTMENTS_ALL or MANAGE_OWN_CALENDAR | Reschedule, 404 for a non-owner doctor |
| POST   | `/api/v1/appointments/{id}/cancel`      | Yes  | MANAGE_APPOINTMENTS_ALL or MANAGE_OWN_CALENDAR | Cancel, 404 for a non-owner doctor |
| POST   | `/api/v1/clinical-documents`            | Yes  | UPLOAD_CLINICAL               | Upload a text-layer PDF under a patient, extracts and stores the text |
| POST   | `/api/v1/clinical-documents/{id}/ingest`| Yes  | UPLOAD_CLINICAL               | Chunk, embed, and index the extracted text at restricted scope |
| GET    | `/api/v1/clinical-documents/{id}/file`  | Yes  | VIEW_CLINICAL                 | Download the stored file, doctor scoped to assigned patients |
| POST   | `/api/v1/rag/query`                     | Yes  | VIEW_CLINICAL                 | Ask a clinical question over ingested documents, doctor scoped to assigned patients |
| GET    | `/api/v1/llm/status`                    | Yes  | admin, operator (role, not permission-gated, see below) | LLM provider config, no network call |
| POST   | `/api/v1/llm/ping`                      | Yes  | admin, operator (role, not permission-gated, see below) | Live LLM reachability check         |

Every route marked with a specific permission above gates via `require_permission()` or
`require_any_permission()` (`app/auth/permissions.py`, `app/auth/dependencies.py`), not a
role directly. See `VitalAI RBAC Report - Audit Trail.md` for the full permission-to-role
mapping. Rows marked "any" only require a valid JWT (`get_current_user`), no permission
check. `/api/v1/llm/*` is the one documented exception to the permission model itself,
kept on the older role-based `require_roles()` mechanism since it's infra/ops diagnostics
outside the RBAC taxonomy.

## Rate limiting

`POST /api/v1/auth/login` is rate-limited to 5 requests per minute per IP using
[slowapi](https://github.com/laurents/slowapi). Exceeding the limit returns
`429 Too Many Requests`.

The limit is configurable through `LOGIN_RATE_LIMIT` in `.env` (default `5/minute`).
Accepts any [limits](https://limits.readthedocs.io/en/stable/string-notation.html)
string, for example `10/minute` or `100/hour`.

## LLM provider switch

Set `LLM_PROVIDER` in `.env`:

- `ollama`: dev. Uses `LLM_MODEL` (default `gemma2:9b`) through `OLLAMA_BASE_URL`.
- `bedrock`: staging and prod. Uses `BEDROCK_MODEL_ID` (default Claude Haiku) in `AWS_REGION`.

`app/llm/provider.py` is where the LLM client itself gets constructed: `get_llm()`
switches between Ollama and Bedrock based on `LLM_PROVIDER`, and nothing else builds an
LLM client directly. `config.py` and `routes/llm.py` reference the provider names too,
but only to read settings or report status, not to construct a client.

The RAG embedding path (`app/rag/embeddings.py`) has its own provider switch and is not
yet wired through `get_llm()`. It's a separate instance of the same pattern, currently a
Sprint 2 stub. Worth folding into the same factory before the Bedrock migration, so
there's one place to update instead of two.

## Append-only audit log

The `audit_events` table has database-level triggers that reject `UPDATE` and `DELETE`.
Any attempt to modify a row fails at the database. This is what backs the tamper-evident
claim in the design documentation. It is plain Postgres trigger enforcement, not a
blockchain or distributed ledger.

`tests/test_audit_trigger.py` is the source of truth for this guarantee, since it runs
against real Postgres and proves the trigger fires. See Running tests above for how to
run it. If a migration touching `audit_events` is ever rewritten, that test is what
confirms the guarantee still holds, not this README.

## Known limitations

The triage classifier matches keywords without negation handling, so a phrase like
"no chest pain" still escalates. This fails safe (it over-escalates rather than misses
something urgent) and is tracked as `test_triage_negation_not_urgent_escalates_incorrectly`,
marked `xfail` pending the Phase 3 NLP classifier. Do not patch this with a quick
negation rule without adding tests for the failure cases it introduces.

One contract decision remains open and is tracked in `docs/project_decisions.md`: the
consent state set (current code uses `pending`, `captured`, `withdrawn`, `not_required`,
with no `unclear` state). Code in this repository follows the states above until that
decision is recorded there.

The RBAC role and permission model is fully implemented: see `VitalAI RBAC Report -
Audit Trail.md` (roles `front_desk`, `operator`, `admin`, `doctor`; permission-based
route gating via `require_permission()`/`require_any_permission()`; row-level scoping
for doctors on patients, clinical reads, and their own calendar; per-user permission
grants; a `department` field on `User`; and audit logging on every state-changing
action plus reads of the audit log itself).

The triage consent guard treats `ConsentStatus.NOT_REQUIRED` the same as `PENDING`:
blocked. This isn't a deliberate design choice, `NOT_REQUIRED` is defined in the enum
but nothing in the codebase currently sets a record to that status, so no real case can
hit this path today. Before anything assigns `NOT_REQUIRED` to a case, the guard in
`triage_service.py` needs an explicit branch and a test. Kept rather than removed because (a) it 
likely reflects a real future case type where consent does not apply, and (b) removing it now requires a Postgres enum migration.

## Constraints

This system does not provide clinical decision support, diagnosis, or treatment
recommendations. It is administrative only.

This boundary covers any clinician-facing record access too: where it exists, it
retrieves and displays records as they are. It does not interpret, summarize
clinically, or score them. Clinical judgment stays with the clinician.

Every state-changing operation writes to the audit log with the authenticated actor.

## Security notes

`.env` is gitignored and must never be committed. `.env.example` should only ever
contain placeholder values. If you generate a real secret, it goes in `.env` and
nowhere else.