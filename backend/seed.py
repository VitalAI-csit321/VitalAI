"""
VitalAI — local test seed script
Run from inside the backend/ folder:

    python seed.py

Creates 3 test users + 3 sample cases with consent and triage data.
Requires the database to be running (docker-compose up db).
"""

import asyncio
import sys

# ── make sure app is importable ────────────────────────────────────────────────
sys.path.insert(0, ".")

from app.auth.security import hash_password
from app.database import AsyncSessionLocal, engine
from app.models.audit import AuditEvent
from app.models.base import Base
from app.models.case import IntakeCase, IntakeStatus
from app.models.consent import ConsentRecord, ConsentStatus
from app.models.triage import TriageCategory, TriageResult
from app.models.user import User, UserRole
from app.models.routing import RoutingDecision, RoutingAction
from datetime import UTC, datetime

# ── Test accounts ──────────────────────────────────────────────────────────────
TEST_USERS = [
    {
        "email":     "admin@vitalai.test",
        "password":  "Admin1234!",
        "full_name": "Admin User",
        "role":      UserRole.ADMIN,
    },
    {
        "email":     "ops@vitalai.test",
        "password":  "Ops12345!",
        "full_name": "Ops Manager",
        "role":      UserRole.OPS_MANAGER,
    },
    {
        "email":     "desk@vitalai.test",
        "password":  "Desk1234!",
        "full_name": "Front Desk",
        "role":      UserRole.FRONT_DESK,
    },
]

# ── Sample cases ───────────────────────────────────────────────────────────────
SAMPLE_CASES = [
    {
        "patient_name":    "Emily Zhang",
        "contact_reason":  "Chest pain and difficulty breathing since this morning",
        "contact_channel": "walk_in",
        "notes":           "Patient appears distressed",
        "consent_type":    "administrative",
        # triage keywords that trigger IMMEDIATE
        "keywords":        ["chest pain", "difficulty breathing"],
        "flags":           ["elderly"],
    },
    {
        "patient_name":    "Marcus Williams",
        "contact_reason":  "Follow-up appointment for test results from last week",
        "contact_channel": "phone",
        "notes":           "Referred by Dr Smith",
        "consent_type":    "administrative",
        "keywords":        ["follow-up", "test results"],
        "flags":           [],
    },
    {
        "patient_name":    "Sarah Johnson",
        "contact_reason":  "Routine check-up and prescription renewal",
        "contact_channel": "email",
        "notes":           None,
        "consent_type":    "administrative",
        "keywords":        [],
        "flags":           [],
    },
]


async def seed():
    print("─" * 50)
    print("VitalAI seed script")
    print("─" * 50)

    async with engine.begin() as conn:
        # Create all tables (safe if they already exist)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:

        # ── 1. Create users ────────────────────────────────────────────────────
        print("\n[1/4] Creating test users…")
        created_users = {}
        for u in TEST_USERS:
            user = User(
                email=u["email"],
                hashed_password=hash_password(u["password"]),
                full_name=u["full_name"],
                role=u["role"],
                is_active=True,
            )
            db.add(user)
            await db.flush()
            created_users[u["role"]] = user
            print(f"  ✓ {u['role'].value:12}  {u['email']}  /  {u['password']}")

        admin_user = created_users[UserRole.ADMIN]

        # ── 2. Create intake cases ─────────────────────────────────────────────
        print("\n[2/4] Creating sample intake cases…")
        created_cases = []
        for c in SAMPLE_CASES:
            case = IntakeCase(
                patient_name=c["patient_name"],
                contact_reason=c["contact_reason"],
                contact_channel=c["contact_channel"],
                notes=c["notes"],
                status=IntakeStatus.RECEIVED,
            )
            db.add(case)
            await db.flush()
            created_cases.append((case, c))

            # audit event
            db.add(AuditEvent(
                case_id=case.id,
                actor_id=admin_user.id,
                actor_label=admin_user.email,
                action="intake.created",
                details={"channel": c["contact_channel"]},
            ))
            await db.flush()
            print(f"  ✓ {case.id}  {c['patient_name']}")

        # ── 3. Create consent records (all captured) ───────────────────────────
        print("\n[3/4] Creating consent records…")
        created_consents = []
        for case, c in created_cases:
            consent = ConsentRecord(
                case_id=case.id,
                status=ConsentStatus.CAPTURED,
                consent_type=c["consent_type"],
                captured_at=datetime.now(UTC),
            )
            db.add(consent)
            await db.flush()
            created_consents.append(consent)

            db.add(AuditEvent(
                case_id=case.id,
                actor_id=admin_user.id,
                actor_label=admin_user.email,
                action="consent.captured",
                details={"consent_id": str(consent.id)},
            ))
            await db.flush()
            print(f"  ✓ consent for {case.patient_name}  [{consent.status.value}]")

        # ── 4. Create triage results ───────────────────────────────────────────
        print("\n[4/4] Running triage on cases…")
        triage_configs = [
            (TriageCategory.IMMEDIATE,    0.90, "Urgent keyword detected — immediate escalation",    RoutingAction.DIRECT_ESCALATION, "emergency_queue",  True),
            (TriageCategory.TIME_SENSITIVE, 0.70, "Time-sensitive keyword — human review required", RoutingAction.HUMAN_REVIEW,       "ops_queue",        False),
            (TriageCategory.ROUTINE,      0.80, "Routine administrative matter — normal workflow",   RoutingAction.ADMIN_WORKFLOW,     "admin_queue",      False),
        ]

        for (case, c), consent, (category, confidence, rationale, action, queue, escalated) in zip(created_cases, created_consents, triage_configs):
            triage = TriageResult(
                case_id=case.id,
                category=category,
                confidence=confidence,
                rationale=rationale,
            )
            db.add(triage)
            await db.flush()

            routing = RoutingDecision(
                case_id=case.id,
                triage_id=triage.id,
                action=action,
                target_queue=queue,
                escalated=escalated,
            )
            db.add(routing)
            await db.flush()

            db.add(AuditEvent(
                case_id=case.id,
                actor_id=admin_user.id,
                actor_label=admin_user.email,
                action="triage.performed",
                details={
                    "triage_id":  str(triage.id),
                    "category":   category.value,
                    "confidence": confidence,
                    "escalated":  escalated,
                },
            ))
            await db.flush()
            print(f"  ✓ {case.patient_name:20}  [{category.value}]  escalated={escalated}")

        await db.commit()

    print("\n" + "─" * 50)
    print("Seed complete! Log in with:")
    print()
    print("  ADMIN      admin@vitalai.test   /  Admin1234!")
    print("  OPS MGR    ops@vitalai.test     /  Ops12345!")
    print("  FRONT DESK desk@vitalai.test    /  Desk1234!")
    print()
    print("Backend: http://localhost:8000")
    print("Docs:    http://localhost:8000/docs")
    print("─" * 50)


if __name__ == "__main__":
    asyncio.run(seed())
