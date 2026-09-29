"""Plain helpers for the Review Queue tests. No fixtures."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assignment import DoctorPatientAssignment
from app.models.audit import AuditEvent
from app.models.case import IntakeCase
from app.models.patient import Patient
from app.models.task import Task, TaskCategory, TaskPriority
from app.models.user import User
from tests.agent_fakes import seed_email


async def inbox_task(
    db: AsyncSession,
    *,
    category: TaskCategory = TaskCategory.GENERAL_ADMINISTRATIVE,
    patient: Patient | None = None,
    priority: TaskPriority = TaskPriority.MEDIUM,
) -> Task:
    """An ingested email's Task (seed_email), optionally about a known patient."""
    _, task = await seed_email(db, category=category)
    task.priority = priority
    if patient is not None:
        case = await db.get(IntakeCase, task.case_id)
        assert case is not None
        case.patient_id = patient.id
        case.patient_name = patient.name
    await db.commit()
    return task


async def assign(db: AsyncSession, doctor: User, patient: Patient) -> None:
    db.add(
        DoctorPatientAssignment(doctor_id=doctor.id, patient_id=patient.id, assigned_by=doctor.id)
    )
    await db.commit()


async def events(db: AsyncSession, action: str) -> list[AuditEvent]:
    result = await db.execute(select(AuditEvent).where(AuditEvent.action == action))
    return list(result.scalars().all())
