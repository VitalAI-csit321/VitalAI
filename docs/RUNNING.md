# Running the full stack

Two terminals. Backend on `:8000`, frontend on `:5173`. CORS is already
configured for that frontend origin.

---

## 1. Backend

### Option A — Docker Compose (recommended)

Brings up Postgres+pgvector, Redis, MinIO, Ollama and the API together.

```bash
cd backend
cp .env.example .env
```

Generate a real secret and set it as `JWT_SECRET_KEY` in `.env`:

```bash
python -c "import secrets; print(secrets.token_urlsafe())"
```

Then:

```bash
docker compose up --build          # wait for the API to report ready
docker compose exec api alembic upgrade head
docker compose exec api python -m scripts.seed_dev_data
```

### Option B — local Postgres, no Docker

Needs Python 3.13 and a Postgres instance with the `pgvector` extension
available.

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env               # set JWT_SECRET_KEY and DATABASE_URL
alembic upgrade head
python -m scripts.seed_dev_data
uvicorn app.main:app --reload
```

Check it's up: <http://localhost:8000/health> should return `{"status":"ok",...}`.
Interactive API docs: <http://localhost:8000/docs>.

---

## 2. Frontend

New terminal:

```bash
cd frontend
cp .env.example .env               # VITE_API_BASE_URL=http://localhost:8000
npm install
npm run dev
```

Open <http://localhost:5173>. You'll land on the login page.

---

## 3. Sign in

The seed script creates one user per role. All share the same dev password:

| Email | Role | Password |
| --- | --- | --- |
| `s.kapoor@royalmelb.health` | admin | `password123` |
| `m.alvarez@royalmelb.health` | ops_manager | `password123` |
| `j.doe@royalmelb.health` | front_desk | `password123` |

Sign in as the admin to see everything — the Users and Audit endpoints are
admin-only.

`seed_dev_data` is safe to re-run; it skips records that already exist.

---

## What to click through

| Page | What's live |
| --- | --- |
| **Dashboard** | The four count tiles come from real endpoints. "Open cases" should equal the number of seeded cases. The weekly chart and pending-reviews list are placeholder. |
| **Patients** | Rows come from real intake cases. Search filters server-side. MRN / DOB / gender are synthesized (no patient table yet). |
| **Patient onboarding** | Fills the 5-step wizard. Finishing creates a real intake case; the extra fields are stored in the case notes. |
| **Consent queue** | Real consent records joined to cases. Tiles count pending / complete / review from live data. |
| **Consent capture** | Signature pad draws; Submit navigates to the success screen. |
| **Records** | Document list is placeholder. The RAG query endpoint behind it needs Postgres+pgvector and a running embedding provider. |
| **Inbox** | Fully placeholder — no messaging backend exists yet. |
| **Review Queue / Escalations / Audit / Settings** | Titled placeholders; designs not yet approved. Their endpoints exist. |

---

## Troubleshooting

**Login fails with a network error, or the browser console shows a CORS error.**
The backend's `CORS_ORIGINS` must include the exact frontend origin. Default is
`http://localhost:5173,http://127.0.0.1:5173`. If you run Vite on another port,
add it to `CORS_ORIGINS` in `backend/.env` and restart the API. Note
`localhost` and `127.0.0.1` are different origins to a browser.

**Login returns 401 with correct-looking details.**
Run the seed script — without it there are no users. Confirm with
`GET /api/v1/auth/users` in the API docs after signing in as admin.

**Login returns 429.**
The login endpoint is rate-limited to 5 requests/minute. Wait a minute.

**Frontend loads but every request fails.**
Check `VITE_API_BASE_URL` in `frontend/.env` matches where the API is actually
listening. Vite only reads `.env` at startup — restart `npm run dev` after
changing it.

**`alembic upgrade head` fails on the vector migration.**
The database must be `pgvector/pgvector:pg16` (or Postgres with the `vector`
extension installed). Plain `postgres:16` will not work.
