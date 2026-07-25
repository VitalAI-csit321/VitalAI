"""Seed development data so the frontend has something to log into and show.

Creates one user per role plus a handful of intake cases with consent records in
mixed states, so the dashboard tiles, patients table and consent queue all render
with realistic data.

Safe to re-run: it skips users and cases that already exist rather than
duplicating them.

    cd backend
    python -m scripts.seed_dev_data

Respects DATABASE_URL from the environment/.env, so it works against Docker
Postgres or a local instance. Run it AFTER `alembic upgrade head`.

Development only. Every record here is synthetic.
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.security import hash_password
from app.config import settings
from app.models.case import IntakeCase, IntakeStatus
from app.models.consent import ConsentRecord
from app.models.human_review import HumanReviewTask, TaskType, TaskStatus, ConsentStatus
from app.models.user import User, UserRole

DEV_PASSWORD = "password123"

USERS = [
    ("s.kapoor@royalmelb.health", "Sanjay Kapoor", UserRole.ADMIN),
    ("m.alvarez@royalmelb.health", "Maria Alvarez", UserRole.OPERATOR),
    ("j.doe@royalmelb.health", "Jamie Doe", UserRole.FRONT_DESK),
    ("d.kapoor@royalmelb.health", "Sanjay Kapoor", UserRole.DOCTOR),
]

# (patient_name, contact_reason, channel, consent_state)
CASES = [
    ("Emily Zhang", "Chest pain since this morning", "phone", ConsentStatus.CAPTURED),
    ("Marcus Williams", "Follow-up on surgical procedure", "email", ConsentStatus.PENDING),
    ("Sarah Johnson", "Requesting test results", "phone", ConsentStatus.CAPTURED),
    ("David Chen", "Data sharing authorisation", "portal", ConsentStatus.CAPTURED),
    ("Lisa Anderson", "Routine checkup booking", "phone", ConsentStatus.PENDING),
    ("James Thompson", "Referral to specialist", "email", ConsentStatus.CAPTURED),
    ("Priya Nair", "Medication query", "phone", ConsentStatus.WITHDRAWN),
    ("Tom Baker", "Insurance claim question", "email", ConsentStatus.PENDING),
]


async def seed(session: AsyncSession) -> None:
    created_users = 0
    for email, full_name, role in USERS:
        existing = await session.scalar(select(User).where(User.email == email))
        if existing:
            continue
        session.add(
            User(
                email=email,
                hashed_password=hash_password(DEV_PASSWORD),
                full_name=full_name,
                role=role,
            )
        )
        created_users += 1

    created_cases = 0
    for patient_name, reason, channel, consent_state in CASES:
        existing = await session.scalar(
            select(IntakeCase).where(IntakeCase.patient_name == patient_name)
        )
        if existing:
            continue
        case = IntakeCase(
            patient_name=patient_name,
            contact_reason=reason,
            contact_channel=channel,
            status=IntakeStatus.RECEIVED,
        )
        session.add(case)
        await session.flush()
        session.add(
            ConsentRecord(
                case_id=case.id,
                status=consent_state,
                consent_type="administrative",
            )
        )
        created_cases += 1


        # Seed review tasks so Review Queue is populated
        if created_cases > 0:
            from sqlalchemy import select as _select
            all_cases = (await session.execute(_select(IntakeCase).limit(8))).scalars().all()
            task_types = [TaskType.TRIAGE_REVIEW, TaskType.CONSENT_REVIEW, TaskType.ESCALATION_REVIEW]
            task_statuses = [TaskStatus.PENDING, TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED, TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.PENDING, TaskStatus.COMPLETED]
            for i, case in enumerate(all_cases):
                existing_task = (await session.execute(
                    _select(HumanReviewTask).where(HumanReviewTask.case_id == case.id)
                )).scalar_one_or_none()
                if not existing_task:
                    session.add(HumanReviewTask(
                        case_id=case.id,
                        task_type=task_types[i % len(task_types)],
                        status=task_statuses[i % len(task_statuses)],
                    ))

    await session.commit()

    print(f"Seeded {created_users} user(s) and {created_cases} case(s).")
    if created_users:
        print("\nSign in with any of these (all share the same dev password):")
        for email, _, role in USERS:
            print(f"  {email:<32} {role.value:<12} password: {DEV_PASSWORD}")


async def main() -> None:
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await seed(session)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
