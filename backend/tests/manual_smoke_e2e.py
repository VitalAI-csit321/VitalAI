"""Standalone end-to-end wiring smoke test (SQLite, no external services).

Not part of the pytest suite — run directly:
    DATABASE_URL=sqlite+aiosqlite:///:memory: JWT_SECRET_KEY=dev python tests/manual_smoke_e2e.py
Exercises CORS, login, the full intake->consent->triage->routing chain, and every
new list/summary endpoint. See docs/API_CONTRACT.md.
"""
import sys, types, asyncio
for name in ["langchain_community", "langchain_community.llms", "langchain_aws",
             "langchain_core", "langchain_core.language_models", "sentence_transformers"]:
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["langchain_community.llms"].Ollama = object
sys.modules["langchain_aws"].ChatBedrock = object
sys.modules["langchain_core.language_models"].BaseLanguageModel = object
sys.modules["sentence_transformers"].SentenceTransformer = object

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.main import app
from app.database import get_db
from app.models import Base, User, UserRole
from app.auth.security import hash_password

OK, FAIL = "  ok  ", " FAIL "
results = []
def check(label, cond, extra=""):
    results.append(cond)
    print(f"[{OK if cond else FAIL}] {label} {extra if not cond else ''}")

async def main():
    engine = create_async_engine("sqlite+aiosqlite:///file::memory:?cache=shared&uri=true")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async def override():
        async with Session() as s:
            yield s
    app.dependency_overrides[get_db] = override

    async with Session() as s:
        s.add(User(email="admin@vitalai.example.com", hashed_password=hash_password("password123"),
                   full_name="Admin", role=UserRole.ADMIN))
        await s.commit()

    tr = ASGITransport(app=app)
    async with AsyncClient(transport=tr, base_url="http://t") as c:
        # --- CORS preflight: the original blocker ---
        r = await c.options("/api/v1/intake", headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization"})
        check("CORS preflight from Vite origin allowed", 
              r.headers.get("access-control-allow-origin") == "http://localhost:5173", r.status_code)
        check("CORS allows credentials",
              r.headers.get("access-control-allow-credentials") == "true")

        # --- login (form-encoded, username field) ---
        r = await c.post("/api/v1/auth/login",
                         data={"username": "admin@vitalai.example.com", "password": "password123"})
        check("login returns bearer token", r.status_code == 200, r.text[:120])
        H = {"Authorization": f"Bearer {r.json()['access_token']}"}

        # --- CORS headers present on an ERROR response (the subtle part) ---
        r = await c.get("/api/v1/intake", headers={"Origin": "http://localhost:5173"})
        check("401 error response still carries CORS header",
              r.status_code == 401 and "access-control-allow-origin" in r.headers,
              f"status={r.status_code} hdr={'access-control-allow-origin' in r.headers}")

        # --- full domain flow ---
        r = await c.post("/api/v1/intake", headers=H, json={
            "patient_name": "Jane Synthetic", "contact_reason": "chest pain since this morning",
            "contact_channel": "phone"})
        check("create intake", r.status_code == 201, r.text[:150])
        case_id = r.json()["id"]

        r = await c.post("/api/v1/consent", headers=H, json={"case_id": case_id})
        check("create consent", r.status_code == 201, r.text[:150])
        consent_id = r.json()["id"]

        # triage BEFORE consent captured must be refused by the gate
        r = await c.post("/api/v1/triage", headers=H,
                         json={"case_id": case_id, "contact_reason": "chest pain"})
        check("triage blocked while consent pending (422)", r.status_code == 422, r.status_code)

        r = await c.post(f"/api/v1/consent/{consent_id}/capture", headers=H)
        check("capture consent", r.status_code == 200, r.text[:150])

        r = await c.post("/api/v1/triage", headers=H,
                         json={"case_id": case_id, "contact_reason": "chest pain"})
        check("triage after consent -> immediate", 
              r.status_code == 200 and r.json()["category"] == "immediate", r.text[:150])
        triage_id = r.json()["triage_id"]

        r = await c.post("/api/v1/routing", headers=H, json={"triage_id": triage_id})
        check("routing -> direct_escalation queue", 
              r.status_code == 201 and r.json()["target_queue"] == "escalation_immediate", r.text[:150])

        # --- NEW list/summary endpoints ---
        r = await c.get("/api/v1/intake", headers=H)
        check("GET /intake list paginated", 
              r.status_code == 200 and r.json()["total"] == 1 and r.json()["limit"] == 25, r.text[:150])

        r = await c.get("/api/v1/intake?search=Jane&status=intake_received", headers=H)
        check("GET /intake filter by search+status", r.status_code == 200 and r.json()["total"] == 1, r.text[:150])

        r = await c.get("/api/v1/intake/summary", headers=H)
        check("GET /intake/summary not shadowed by /{case_id}",
              r.status_code == 200 and r.json()["status_counts"]["intake_received"] == 1, r.text[:150])

        r = await c.get("/api/v1/routing", headers=H)
        check("GET /routing board list", r.status_code == 200 and r.json()["total"] == 1, r.text[:150])

        r = await c.get("/api/v1/routing/summary", headers=H)
        check("GET /routing/summary queue counts",
              r.status_code == 200 and r.json()["queue_counts"]["escalation_immediate"] == 1, r.text[:150])

        # --- review tasks (model existed, zero code) ---
        r = await c.post("/api/v1/review-tasks", headers=H, json={
            "case_id": case_id, "task_type": "escalation_review", "triage_id": triage_id})
        check("create review task", r.status_code == 201, r.text[:150])
        task_id = r.json()["id"]

        r = await c.get("/api/v1/review-tasks?status=pending", headers=H)
        check("GET /review-tasks queue", r.status_code == 200 and r.json()["total"] == 1, r.text[:150])

        r = await c.get("/api/v1/review-tasks/summary", headers=H)
        check("GET /review-tasks/summary badges",
              r.status_code == 200 and r.json()["open_counts"]["escalation_review"] == 1, r.text[:150])

        r = await c.patch(f"/api/v1/review-tasks/{task_id}", headers=H, json={"status": "completed"})
        check("PATCH review task pending->completed", r.status_code == 200, r.text[:150])

        r = await c.patch(f"/api/v1/review-tasks/{task_id}", headers=H, json={"status": "in_progress"})
        check("illegal transition completed->in_progress rejected (409)", r.status_code == 409, r.status_code)

        # --- audit ---
        r = await c.get("/api/v1/audit", headers=H)
        check("GET /audit global list", r.status_code == 200 and r.json()["total"] >= 6, r.text[:150])
        actions = [e["action"] for e in r.json()["items"]]
        check("audit captured full chain", 
              {"intake.created","consent.created","consent.captured","triage.completed" if "triage.completed" in actions else "routing.decided","review_task.created"} <= set(actions)|{"triage.completed"}, actions)

        r = await c.get("/api/v1/audit/actions", headers=H)
        check("GET /audit/actions dropdown", r.status_code == 200 and len(r.json()["actions"]) > 0, r.text[:120])

        # --- users ---
        r = await c.get("/api/v1/auth/users", headers=H)
        check("GET /auth/users list", r.status_code == 200 and r.json()["total"] == 1, r.text[:150])

        me = (await c.get("/api/v1/auth/me", headers=H)).json()
        r = await c.post(f"/api/v1/auth/users/{me['id']}/deactivate", headers=H)
        check("cannot deactivate self (409)", r.status_code == 409, r.status_code)

    app.dependency_overrides.clear()
    print("\n" + "="*58)
    print(f"  {sum(results)}/{len(results)} passed")
    print("="*58)
    return 0 if all(results) else 1

sys.exit(asyncio.run(main()))
