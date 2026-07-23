from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_password
from app.models.audit import AuditEvent
from app.models.patient import Gender, PatientStatus
from app.models.user import User, UserRole
from app.schemas.patient import PatientCreate
from app.services import patient_service


def _actor() -> User:
    return User(
        email="reg@example.com",
        hashed_password=hash_password("pw"),
        full_name="Reg",
        role=UserRole.FRONT_DESK,
    )


async def test_create_patient_generates_unique_mrn(db_session: AsyncSession):
    actor = _actor()
    db_session.add(actor)
    await db_session.commit()

    p1 = await patient_service.create_patient(
        db_session, PatientCreate(name="Ada", dob=date(1990, 1, 1), gender=Gender.FEMALE), actor
    )
    p2 = await patient_service.create_patient(
        db_session, PatientCreate(name="Bea", dob=date(1991, 2, 2), gender=Gender.FEMALE), actor
    )

    assert p1.mrn != p2.mrn
    assert p1.mrn.startswith("MRN-")
    assert p1.status == PatientStatus.PENDING


async def test_create_patient_writes_audit_event(db_session: AsyncSession):
    actor = _actor()
    db_session.add(actor)
    await db_session.commit()

    patient = await patient_service.create_patient(
        db_session, PatientCreate(name="Cy", dob=date(1992, 3, 3), gender=Gender.MALE), actor
    )

    result = await db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "patient.registered")
    )
    events = result.scalars().all()
    assert len(events) == 1
    assert events[0].details["patient_id"] == str(patient.id)


async def test_list_patients_search_by_partial_name(db_session: AsyncSession):
    actor = _actor()
    db_session.add(actor)
    await db_session.commit()

    await patient_service.create_patient(
        db_session,
        PatientCreate(name="Jane Smith", dob=date(1990, 1, 1), gender=Gender.FEMALE),
        actor,
    )
    await patient_service.create_patient(
        db_session, PatientCreate(name="John Doe", dob=date(1991, 1, 1), gender=Gender.MALE), actor
    )

    items, total, _ = await patient_service.list_patients(db_session, search="smith")
    assert total == 1
    assert items[0].name == "Jane Smith"


async def test_list_patients_search_by_partial_mrn(db_session: AsyncSession):
    actor = _actor()
    db_session.add(actor)
    await db_session.commit()

    patient = await patient_service.create_patient(
        db_session, PatientCreate(name="X", dob=date(1990, 1, 1), gender=Gender.MALE), actor
    )
    mrn_fragment = patient.mrn[4:8]  # skip "MRN-" prefix

    items, total, _ = await patient_service.list_patients(db_session, search=mrn_fragment)
    assert total == 1
    assert items[0].id == patient.id


async def test_list_patients_status_filter(db_session: AsyncSession):
    actor = _actor()
    db_session.add(actor)
    await db_session.commit()

    p = await patient_service.create_patient(
        db_session, PatientCreate(name="Y", dob=date(1990, 1, 1), gender=Gender.MALE), actor
    )
    p.status = PatientStatus.ACTIVE
    await db_session.commit()

    items, total, _ = await patient_service.list_patients(db_session, status=PatientStatus.ACTIVE)
    assert total == 1
    assert items[0].id == p.id

    items, total, _ = await patient_service.list_patients(db_session, status=PatientStatus.INACTIVE)
    assert total == 0


async def test_list_patients_counts_are_global_not_filtered(db_session: AsyncSession):
    actor = _actor()
    db_session.add(actor)
    await db_session.commit()

    p1 = await patient_service.create_patient(
        db_session, PatientCreate(name="A1", dob=date(1990, 1, 1), gender=Gender.MALE), actor
    )
    p1.status = PatientStatus.ACTIVE
    p2 = await patient_service.create_patient(
        db_session, PatientCreate(name="A2", dob=date(1990, 1, 1), gender=Gender.MALE), actor
    )
    p2.status = PatientStatus.INACTIVE
    await db_session.commit()

    _, _, counts = await patient_service.list_patients(db_session, search="nonexistent-name")
    assert counts["active"] == 1
    assert counts["inactive"] == 1
    assert counts["pending"] == 0


async def test_list_patients_pagination(db_session: AsyncSession):
    actor = _actor()
    db_session.add(actor)
    await db_session.commit()

    for i in range(3):
        await patient_service.create_patient(
            db_session, PatientCreate(name=f"P{i}", dob=date(1990, 1, 1), gender=Gender.MALE), actor
        )

    items, total, _ = await patient_service.list_patients(db_session, limit=2, offset=0)
    assert total == 3
    assert len(items) == 2

    items, total, _ = await patient_service.list_patients(db_session, limit=2, offset=2)
    assert len(items) == 1
