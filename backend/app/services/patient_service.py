import operator
import secrets
from functools import reduce
from uuid import UUID

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.scoping import assigned_patient_ids_subquery
from app.models.case import IntakeCase
from app.models.consent import ConsentStatus
from app.models.patient import PROFILE_FIELDS, Patient, PatientStatus
from app.models.user import User
from app.schemas.patient import PatientCreate, PatientUpdate
from app.services import consent_service
from app.services.audit_service import record_event

_MRN_GENERATION_ATTEMPTS = 5


class ProvisionalPatientError(Exception):
    """The patient is provisional: created from an inbound message, not yet
    verified by staff. Not bookable, and no clinical records (spec §9.0a)."""


class PromotionRefusedError(Exception):
    """promote_patient's preconditions do not hold."""


async def assert_not_provisional(db: AsyncSession, patient_id: UUID | None) -> None:
    patient = await db.get(Patient, patient_id) if patient_id is not None else None
    if patient is not None and patient.is_provisional:
        raise ProvisionalPatientError(
            f"Patient {patient_id} is provisional; staff must complete their registration first"
        )


async def _generate_unique_mrn(db: AsyncSession) -> str:
    for _ in range(_MRN_GENERATION_ATTEMPTS):
        candidate = f"MRN-{secrets.token_hex(4).upper()}"
        existing = await db.execute(select(Patient.id).where(Patient.mrn == candidate))
        if existing.scalar_one_or_none() is None:
            return candidate
    raise RuntimeError(f"Could not generate a unique MRN after {_MRN_GENERATION_ATTEMPTS} attempts")


def missing_profile_fields(patient: Patient) -> list[str]:
    return [f for f in PROFILE_FIELDS if not getattr(patient, f)]


def is_profile_complete(patient: Patient) -> bool:
    return not missing_profile_fields(patient) and bool(
        patient.name and patient.dob and patient.gender
    )


async def create_patient(db: AsyncSession, payload: PatientCreate, actor: User) -> Patient:
    mrn = await _generate_unique_mrn(db)
    patient = Patient(
        mrn=mrn,
        name=payload.name,
        dob=payload.dob,
        gender=payload.gender,
        status=PatientStatus.PENDING,
    )
    for field in PROFILE_FIELDS:
        value = getattr(payload, field, None)
        if value is not None:
            setattr(patient, field, value)
    patient.status = PatientStatus.ACTIVE if is_profile_complete(patient) else PatientStatus.PENDING
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

    for field in PROFILE_FIELDS:
        value = getattr(payload, field, None)
        if value is not None:
            setattr(patient, field, value)
            changes[field] = str(value)

    if payload.status is not None:
        patient.status = payload.status
        changes["status"] = payload.status.value
    elif patient.status != PatientStatus.INACTIVE:
        patient.status = (
            PatientStatus.ACTIVE if is_profile_complete(patient) else PatientStatus.PENDING
        )
    # Only promote_patient (a human, with explicit consent on file) makes a
    # provisional patient ACTIVE, however complete the profile or the edit.
    if patient.is_provisional and patient.status == PatientStatus.ACTIVE:
        patient.status = PatientStatus.PENDING

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


async def create_provisional_patient(
    db: AsyncSession,
    *,
    case_id: UUID,
    name: str,
    email: str | None,
    phone: str | None,
    dob,
    actor: User,
) -> Patient:
    """A patient known only from an inbound message (spec §9.0), linked to its
    case. PENDING and provisional until a human promotes them."""
    patient = Patient(
        mrn=await _generate_unique_mrn(db),
        name=name,
        dob=dob,
        email=email,
        phone=phone,
        status=PatientStatus.PENDING,
        is_provisional=True,
    )
    db.add(patient)
    await db.flush()
    case = await db.get(IntakeCase, case_id)
    if case is not None:
        case.patient_id = patient.id
        case.patient_name = patient.name
    await record_event(
        db,
        actor=actor,
        case_id=case_id,
        action="patient.provisional_created",
        details={"patient_id": str(patient.id), "mrn": patient.mrn},
    )
    await db.commit()
    await db.refresh(patient)
    return patient


async def promote_patient(db: AsyncSession, patient_id: UUID, actor: User) -> Patient | None:
    """Provisional -> registered. Human-only (the route needs REGISTER_PATIENT),
    and only with explicit consent: a CAPTURED record that is not the implied
    consent onboarding recorded. None if there is no such patient."""
    patient = await db.get(Patient, patient_id)
    if patient is None:
        return None
    if patient.purged_at is not None:
        raise PromotionRefusedError(f"Patient {patient_id} was purged")
    if not patient.is_provisional:
        raise PromotionRefusedError(f"Patient {patient_id} is not provisional")
    consents = await consent_service.list_consents_for_patient(db, patient.id)
    if not any(
        c.status == ConsentStatus.CAPTURED
        and c.consent_type != consent_service.IMPLIED_INBOUND_CONTACT
        for c in consents
    ):
        raise PromotionRefusedError(
            f"Patient {patient_id} has no explicit captured consent; capture it first"
        )
    before = {"is_provisional": True, "status": patient.status.value}
    patient.is_provisional = False
    if patient.status != PatientStatus.INACTIVE:
        patient.status = (
            PatientStatus.ACTIVE if is_profile_complete(patient) else PatientStatus.PENDING
        )
    await record_event(
        db,
        actor=actor,
        action="patient.promoted",
        details={
            "patient_id": str(patient.id),
            "before": before,
            "after": {"is_provisional": False, "status": patient.status.value},
        },
    )
    await db.commit()
    await db.refresh(patient)
    return patient


async def get_patient_by_id(
    db: AsyncSession,
    patient_id: UUID,
    doctor_id: UUID | None = None,
    include_provisional: bool = False,
) -> Patient | None:
    query = select(Patient).where(Patient.id == patient_id)
    if not include_provisional:
        query = query.where(Patient.is_provisional.is_(False))
    if doctor_id is not None:
        query = query.where(Patient.id.in_(assigned_patient_ids_subquery(doctor_id)))
    return (await db.execute(query)).scalar_one_or_none()


async def list_patients(
    db: AsyncSession,
    search: str | None = None,
    status: PatientStatus | None = None,
    sort: str | None = None,
    limit: int = 20,
    offset: int = 0,
    doctor_id: UUID | None = None,
    include_provisional: bool = False,
) -> tuple[list[Patient], int, dict[str, int]]:
    """include_provisional: only for callers holding REGISTER_PATIENT, so staff
    can find and promote them. Takes no actor, so the route decides."""
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
    # Like doctor scoping, hidden from the counts too.
    visible = None if include_provisional else Patient.is_provisional.is_(False)
    if visible is not None:
        filters.append(visible)

    items_query = select(Patient)
    count_query = select(func.count()).select_from(Patient)
    counts_query = select(Patient.status, func.count()).group_by(Patient.status)
    if scope_filter is not None:
        counts_query = counts_query.where(scope_filter)
    if visible is not None:
        counts_query = counts_query.where(visible)
    for condition in filters:
        items_query = items_query.where(condition)
        count_query = count_query.where(condition)

    if sort == "missing_fields":
        # insurance_expiry is the one Date column in PROFILE_FIELDS (the rest are
        # String/Text): comparing a date column to "" is valid under SQLite's
        # dynamic typing but raises "operator does not exist: date = character
        # varying" on Postgres, so it only checks IS NULL.
        def _is_missing(field: str):
            column = getattr(Patient, field)
            if field == "insurance_expiry":
                return column.is_(None)
            return or_(column.is_(None), column == "")

        missing_count = reduce(
            operator.add, (case((_is_missing(f), 1), else_=0) for f in PROFILE_FIELDS)
        )
        items_query = items_query.order_by(missing_count.asc(), Patient.created_at.desc())
    else:
        items_query = items_query.order_by(Patient.created_at.desc())

    items_result = await db.execute(items_query.limit(limit).offset(offset))
    items = list(items_result.scalars().all())
    total = (await db.execute(count_query)).scalar_one()

    counts = {s.value: 0 for s in PatientStatus}
    counts_result = await db.execute(counts_query)
    for status_value, count in counts_result.all():
        counts[status_value.value] = count

    return items, total, counts
