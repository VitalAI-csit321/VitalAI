import secrets
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.scoping import assigned_patient_ids_subquery
from app.models.patient import Patient, PatientStatus
from app.models.user import User
from app.schemas.patient import PatientCreate, PatientUpdate
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


async def update_patient(
    db: AsyncSession,
    patient: Patient,
    payload: PatientUpdate,
    actor: User,
) -> Patient:
    changes: dict[str, str] = {}
    if payload.name is not None:
        patient.name = payload.name
        changes["name"] = payload.name
    if payload.dob is not None:
        patient.dob = payload.dob
        changes["dob"] = payload.dob.isoformat()
    if payload.gender is not None:
        patient.gender = payload.gender
        changes["gender"] = payload.gender.value
    if payload.status is not None:
        patient.status = payload.status
        changes["status"] = payload.status.value
    await db.flush()

    await record_event(
        db,
        actor=actor,
        action="patient.updated",
        details={"patient_id": str(patient.id), **changes},
    )
    await db.commit()
    await db.refresh(patient)
    return patient


async def get_patient_by_id(
    db: AsyncSession, patient_id: UUID, doctor_id: UUID | None = None
) -> Patient | None:
    query = select(Patient).where(Patient.id == patient_id)
    if doctor_id is not None:
        query = query.where(Patient.id.in_(assigned_patient_ids_subquery(doctor_id)))
    return (await db.execute(query)).scalar_one_or_none()


async def list_patients(
    db: AsyncSession,
    search: str | None = None,
    status: PatientStatus | None = None,
    limit: int = 20,
    offset: int = 0,
    doctor_id: UUID | None = None,
) -> tuple[list[Patient], int, dict[str, int]]:
    filters = []
    if search:
        term = f"%{search}%"
        filters.append(or_(Patient.name.ilike(term), Patient.mrn.ilike(term)))
    if status is not None:
        filters.append(Patient.status == status)

    # Doctor scoping applies to the status-counts summary too (unlike search/status,
    # which the counts intentionally ignore, per Phase 2): a doctor must never see
    # a breakdown that includes patients they can't open via the list below it.
    scope_filter = (
        Patient.id.in_(assigned_patient_ids_subquery(doctor_id)) if doctor_id is not None else None
    )
    if scope_filter is not None:
        filters.append(scope_filter)

    items_query = select(Patient)
    count_query = select(func.count()).select_from(Patient)
    counts_query = select(Patient.status, func.count()).group_by(Patient.status)
    if scope_filter is not None:
        counts_query = counts_query.where(scope_filter)
    for condition in filters:
        items_query = items_query.where(condition)
        count_query = count_query.where(condition)

    items_result = await db.execute(
        items_query.order_by(Patient.created_at.desc()).limit(limit).offset(offset)
    )
    items = list(items_result.scalars().all())
    total = (await db.execute(count_query)).scalar_one()

    counts = {s.value: 0 for s in PatientStatus}
    counts_result = await db.execute(counts_query)
    for status_value, count in counts_result.all():
        counts[status_value.value] = count

    return items, total, counts
