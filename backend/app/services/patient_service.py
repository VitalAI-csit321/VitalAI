import secrets

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.patient import Patient, PatientStatus
from app.models.user import User
from app.schemas.patient import PatientCreate
from app.services.audit_service import record_event

_MRN_GENERATION_ATTEMPTS = 5


async def _generate_unique_mrn(db: AsyncSession) -> str:
    for _ in range(_MRN_GENERATION_ATTEMPTS):
        candidate = f"MRN-{secrets.token_hex(4).upper()}"
        existing = await db.execute(select(Patient.id).where(Patient.mrn == candidate))
        if existing.scalar_one_or_none() is None:
            return candidate
    raise RuntimeError(f"Could not generate a unique MRN after {_MRN_GENERATION_ATTEMPTS} attempts")


async def create_patient(db: AsyncSession, payload: PatientCreate, actor: User) -> Patient:
    mrn = await _generate_unique_mrn(db)
    patient = Patient(
        mrn=mrn,
        name=payload.name,
        dob=payload.dob,
        gender=payload.gender,
        status=PatientStatus.PENDING,
    )
    db.add(patient)
    await db.flush()

    await record_event(
        db,
        actor=actor,
        action="patient.registered",
        details={"patient_id": str(patient.id), "mrn": mrn},
    )
    await db.commit()
    await db.refresh(patient)
    return patient


async def list_patients(
    db: AsyncSession,
    search: str | None = None,
    status: PatientStatus | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Patient], int, dict[str, int]]:
    filters = []
    if search:
        term = f"%{search}%"
        filters.append(or_(Patient.name.ilike(term), Patient.mrn.ilike(term)))
    if status is not None:
        filters.append(Patient.status == status)

    items_query = select(Patient)
    count_query = select(func.count()).select_from(Patient)
    for condition in filters:
        items_query = items_query.where(condition)
        count_query = count_query.where(condition)

    items_result = await db.execute(
        items_query.order_by(Patient.created_at.desc()).limit(limit).offset(offset)
    )
    items = list(items_result.scalars().all())
    total = (await db.execute(count_query)).scalar_one()

    counts = {s.value: 0 for s in PatientStatus}
    counts_result = await db.execute(select(Patient.status, func.count()).group_by(Patient.status))
    for status_value, count in counts_result.all():
        counts[status_value.value] = count

    return items, total, counts
