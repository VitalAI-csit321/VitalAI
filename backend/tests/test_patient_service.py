from datetime import date
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_password
from app.models.audit import AuditEvent
from app.models.patient import Gender, PatientStatus
from app.models.user import User, UserRole
from app.schemas.patient import PatientCreate, PatientUpdate
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
        select(AuditEvent).where(
            AuditEvent.action == "patient.registered", AuditEvent.actor_id == actor.id
        )
    )
    events = result.scalars().all()
    assert len(events) == 1
    assert events[0].details["patient_id"] == str(patient.id)


async def test_list_patients_search_by_partial_name(db_session: AsyncSession):
    actor = _actor()
    db_session.add(actor)
    await db_session.commit()

    # A uuid-suffixed surname, not "Smith"/"Doe": list_patients() searches
    # unscoped across the whole table, and this dev database accumulates
    # real demo patients across sessions, so a common name can collide with
    # pre-existing rows and make total > 1.
    unique_name = f"Zeldenrust{uuid4().hex[:8]}"
    await patient_service.create_patient(
        db_session,
        PatientCreate(name=f"Jane {unique_name}", dob=date(1990, 1, 1), gender=Gender.FEMALE),
        actor,
    )
    await patient_service.create_patient(
        db_session, PatientCreate(name="John Doe", dob=date(1991, 1, 1), gender=Gender.MALE), actor
    )

    items, total, _ = await patient_service.list_patients(db_session, search=unique_name)
    assert total == 1
    assert items[0].name == f"Jane {unique_name}"


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
        db_session,
        PatientCreate(name="StatusFilterTestPatient", dob=date(1990, 1, 1), gender=Gender.MALE),
        actor,
    )
    p.status = PatientStatus.ACTIVE
    await db_session.commit()

    # search scopes to just this test's own patient, so pre-existing rows in a
    # shared dev database can't inflate the count.
    items, total, _ = await patient_service.list_patients(
        db_session, search="StatusFilterTestPatient", status=PatientStatus.ACTIVE
    )
    assert total == 1
    assert items[0].id == p.id

    items, total, _ = await patient_service.list_patients(
        db_session, search="StatusFilterTestPatient", status=PatientStatus.INACTIVE
    )
    assert total == 0


async def test_list_patients_counts_are_global_not_filtered(db_session: AsyncSession):
    actor = _actor()
    db_session.add(actor)
    await db_session.commit()

    # counts must reflect the whole table regardless of the search filter, so this
    # test can't scope the count query to just its own rows the way other tests do.
    # Compare before/after deltas instead of absolute numbers, so pre-existing rows
    # in a shared dev database don't cause a false failure.
    _, _, before = await patient_service.list_patients(db_session, search="nonexistent-name")

    p1 = await patient_service.create_patient(
        db_session, PatientCreate(name="A1", dob=date(1990, 1, 1), gender=Gender.MALE), actor
    )
    p1.status = PatientStatus.ACTIVE
    p2 = await patient_service.create_patient(
        db_session, PatientCreate(name="A2", dob=date(1990, 1, 1), gender=Gender.MALE), actor
    )
    p2.status = PatientStatus.INACTIVE
    await db_session.commit()

    _, _, after = await patient_service.list_patients(db_session, search="nonexistent-name")
    assert after["active"] == before["active"] + 1
    assert after["inactive"] == before["inactive"] + 1
    assert after["pending"] == before["pending"]


def _complete_profile_kwargs() -> dict:
    return dict(
        address="1 Test St", indigenous_status="Not stated", preferred_language="English",
        phone="0400000000", email="test@example.com",
        emergency_contact_name="Jo", emergency_contact_phone="0400000001",
        preferred_communication="Phone", best_time_to_contact="Morning",
        known_conditions="None", current_medications="None", allergies="None",
        insurance_provider="BUPA", policy_number="P1", group_number="N/A",
        insurance_expiry=date(2030, 1, 1), medicare_number="123456789", concession_card="None",
    )


async def test_create_patient_partial_payload_is_pending(db_session: AsyncSession):
    actor = _actor()
    db_session.add(actor)
    await db_session.commit()

    patient = await patient_service.create_patient(
        db_session,
        PatientCreate(name="Partial", dob=date(1990, 1, 1), gender=Gender.MALE, phone="0400000000"),
        actor,
    )
    assert patient.status == PatientStatus.PENDING
    assert "phone" not in patient_service.missing_profile_fields(patient)
    assert "email" in patient_service.missing_profile_fields(patient)


async def test_create_patient_full_payload_is_active(db_session: AsyncSession):
    actor = _actor()
    db_session.add(actor)
    await db_session.commit()

    patient = await patient_service.create_patient(
        db_session,
        PatientCreate(
            name="Complete", dob=date(1990, 1, 1), gender=Gender.MALE, **_complete_profile_kwargs()
        ),
        actor,
    )
    assert patient.status == PatientStatus.ACTIVE
    assert patient_service.missing_profile_fields(patient) == []


async def test_update_patient_explicit_status_overrides_completeness(db_session: AsyncSession):
    actor = _actor()
    db_session.add(actor)
    await db_session.commit()

    patient = await patient_service.create_patient(
        db_session,
        PatientCreate(name="Full", dob=date(1990, 1, 1), gender=Gender.MALE, **_complete_profile_kwargs()),
        actor,
    )
    assert patient.status == PatientStatus.ACTIVE

    updated = await patient_service.update_patient(
        db_session, patient, PatientUpdate(status=PatientStatus.INACTIVE), actor
    )
    assert updated.status == PatientStatus.INACTIVE


async def test_update_patient_field_edit_does_not_reactivate_inactive(db_session: AsyncSession):
    actor = _actor()
    db_session.add(actor)
    await db_session.commit()

    patient = await patient_service.create_patient(
        db_session,
        PatientCreate(
            name="StaysInactive", dob=date(1990, 1, 1), gender=Gender.MALE, **_complete_profile_kwargs()
        ),
        actor,
    )
    await patient_service.update_patient(
        db_session, patient, PatientUpdate(status=PatientStatus.INACTIVE), actor
    )
    assert patient.status == PatientStatus.INACTIVE

    updated = await patient_service.update_patient(
        db_session, patient, PatientUpdate(phone="0499999999"), actor
    )
    assert updated.status == PatientStatus.INACTIVE


async def test_update_patient_completes_profile_and_activates(db_session: AsyncSession):
    actor = _actor()
    db_session.add(actor)
    await db_session.commit()

    patient = await patient_service.create_patient(
        db_session, PatientCreate(name="Filling In", dob=date(1990, 1, 1), gender=Gender.MALE), actor
    )
    assert patient.status == PatientStatus.PENDING

    updated = await patient_service.update_patient(
        db_session, patient, PatientUpdate(**_complete_profile_kwargs()), actor
    )
    assert updated.status == PatientStatus.ACTIVE


async def test_list_patients_pagination(db_session: AsyncSession):
    actor = _actor()
    db_session.add(actor)
    await db_session.commit()

    for i in range(3):
        await patient_service.create_patient(
            db_session,
            PatientCreate(
                name=f"PaginationTestPatient{i}", dob=date(1990, 1, 1), gender=Gender.MALE
            ),
            actor,
        )

    # search scopes pagination to just this test's own patients, so pre-existing
    # rows in a shared dev database can't change the expected total/page sizes.
    items, total, _ = await patient_service.list_patients(
        db_session, search="PaginationTestPatient", limit=2, offset=0
    )
    assert total == 3
    assert len(items) == 2

    items, total, _ = await patient_service.list_patients(
        db_session, search="PaginationTestPatient", limit=2, offset=2
    )
    assert len(items) == 1
