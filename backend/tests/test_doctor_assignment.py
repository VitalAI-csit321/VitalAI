"""Every staff-created or promoted patient gets a doctor (M4 spec, E6)."""

from datetime import date
from uuid import uuid4

from sqlalchemy import select

from app.models.assignment import DoctorPatientAssignment
from app.models.consent import ConsentRecord, ConsentStatus
from app.models.patient import Gender, Patient
from app.models.user import User, UserRole
from app.schemas.patient import PatientCreate
from app.services import assignment_service, patient_service
from app.services.doctor_suggestion import suggest_doctor_for_patient
from scripts import assign_missing_doctors
from tests.review_helpers import assign, events


async def _doctor(db, label: str, *, active: bool = True) -> User:
    doctor = User(
        email=f"doc-{label}-{uuid4().hex[:6]}@example.com",
        hashed_password="h",
        full_name=f"Dr {label}",
        role=UserRole.DOCTOR,
        is_active=active,
    )
    db.add(doctor)
    await db.commit()
    return doctor


async def _busy(db, doctor: User, patients: int) -> None:
    """Give a doctor some existing patients."""
    for i in range(patients):
        p = Patient(mrn=f"MRN-BUSY{uuid4().hex[:6]}", name=f"Busy {i}")
        db.add(p)
        await db.flush()
        db.add(DoctorPatientAssignment(doctor_id=doctor.id, patient_id=p.id, assigned_by=doctor.id))
    await db.commit()


async def _doctors_of(db, patient_id) -> set:
    rows = await db.scalars(
        select(DoctorPatientAssignment.doctor_id).where(
            DoctorPatientAssignment.patient_id == patient_id
        )
    )
    return set(rows.all())


def _new(preferred=None) -> PatientCreate:
    return PatientCreate(
        name="New Patient",
        dob=date(1980, 5, 5),
        gender=Gender.MALE,
        preferred_doctor_id=preferred,
    )


async def test_the_suggestion_skips_inactive_doctors(db_session, patient):
    await _doctor(db_session, "gone", active=False)  # zero patients, but inactive
    active = await _doctor(db_session, "here")
    await _busy(db_session, active, 1)
    assert await suggest_doctor_for_patient(db_session, patient.id) == active.id


async def test_create_assigns_the_preferred_doctor(db_session, admin_user):
    quiet = await _doctor(db_session, "quiet")
    preferred = await _doctor(db_session, "preferred")
    await _busy(db_session, preferred, 3)

    created = await patient_service.create_patient(db_session, _new(preferred.id), admin_user)

    assert created.preferred_doctor_id == preferred.id
    assert await _doctors_of(db_session, created.id) == {preferred.id}
    assert quiet.id not in await _doctors_of(db_session, created.id)
    (event,) = await events(db_session, "patient.doctor_assigned")
    assert event.details == {
        "patient_id": str(created.id),
        "doctor_id": str(preferred.id),
        "reason": "preference",
    }


async def test_no_preference_assigns_the_least_loaded_active_doctor(db_session, admin_user):
    busy = await _doctor(db_session, "busy")
    await _busy(db_session, busy, 2)
    quiet = await _doctor(db_session, "quiet")

    created = await patient_service.create_patient(db_session, _new(), admin_user)

    assert await _doctors_of(db_session, created.id) == {quiet.id}
    (event,) = await events(db_session, "patient.doctor_assigned")
    assert event.details["reason"] == "least_loaded"


async def test_a_preferred_doctor_who_has_since_left_falls_back(db_session, admin_user):
    leaving = await _doctor(db_session, "leaving")
    other = await _doctor(db_session, "other")
    created = await patient_service.create_patient(db_session, _new(leaving.id), admin_user)
    # Left after the preference was recorded: ensure_doctor runs again later
    # (promotion, the one-off script) and must not hand them a patient.
    leaving.is_active = False
    await db_session.execute(
        DoctorPatientAssignment.__table__.delete().where(
            DoctorPatientAssignment.patient_id == created.id
        )
    )
    await db_session.commit()

    doctor_id = await assignment_service.ensure_doctor(db_session, created, admin_user)

    assert doctor_id == other.id


async def test_an_inactive_preferred_doctor_is_refused_at_registration(db_session, admin_user):
    gone = await _doctor(db_session, "gone", active=False)
    try:
        await patient_service.create_patient(db_session, _new(gone.id), admin_user)
    except patient_service.PreferredDoctorError:
        pass
    else:
        raise AssertionError("an inactive preferred doctor was accepted")


async def test_an_existing_doctor_is_left_alone(db_session, patient, doctor_user, admin_user):
    await assign(db_session, doctor_user, patient)
    await _doctor(db_session, "quiet")
    assert await assignment_service.ensure_doctor(db_session, patient, admin_user) is None
    assert await _doctors_of(db_session, patient.id) == {doctor_user.id}
    assert await events(db_session, "patient.doctor_assigned") == []


async def test_a_provisional_patient_gets_no_doctor_until_promoted(
    db_session, patient, doctor_user, admin_user
):
    patient.is_provisional = True
    await db_session.commit()
    assert await assignment_service.ensure_doctor(db_session, patient, admin_user) is None
    assert await _doctors_of(db_session, patient.id) == set()

    from app.models.case import IntakeCase

    contact = IntakeCase(patient_id=patient.id, contact_reason="x", contact_channel="email")
    db_session.add(contact)
    await db_session.flush()
    db_session.add(
        ConsentRecord(case_id=contact.id, status=ConsentStatus.CAPTURED, consent_type="treatment")
    )
    await db_session.commit()
    await patient_service.promote_patient(db_session, patient.id, admin_user)

    assert await _doctors_of(db_session, patient.id) == {doctor_user.id}


async def test_staff_change_the_patients_doctor(db_session, patient, doctor_user, admin_user):
    await assign(db_session, doctor_user, patient)
    new = await _doctor(db_session, "new")

    await assignment_service.change_doctor(db_session, patient, new.id, admin_user)

    assert await _doctors_of(db_session, patient.id) == {new.id}
    (event,) = await events(db_session, "patient.doctor_assigned")
    assert event.details["reason"] == "staff"


async def test_the_change_doctor_route_is_for_assigners(
    client, patient, doctor_user, operator_headers, front_desk_headers, db_session
):
    new = await _doctor(db_session, "new")
    url = f"/api/v1/patients/{patient.id}/doctor"
    assert (
        await client.put(url, json={"doctor_id": str(new.id)}, headers=front_desk_headers)
    ).status_code == 403
    response = await client.put(url, json={"doctor_id": str(new.id)}, headers=operator_headers)
    assert response.status_code == 200
    assert response.json()["doctor_id"] == str(new.id)
    assert response.json()["doctor_name"] == new.full_name


async def test_patient_out_shows_the_doctor_and_the_preference(
    client, patient, doctor_user, admin_headers, db_session
):
    await assign(db_session, doctor_user, patient)
    patient.preferred_doctor_id = doctor_user.id
    await db_session.commit()
    body = (await client.get(f"/api/v1/patients/{patient.id}", headers=admin_headers)).json()
    assert (body["doctor_id"], body["doctor_name"], body["preferred_doctor_id"]) == (
        str(doctor_user.id),
        doctor_user.full_name,
        str(doctor_user.id),
    )


async def test_the_one_off_script_dry_run_changes_nothing(db_session, patient, admin_user):
    await _doctor(db_session, "quiet")
    planned = await assign_missing_doctors.run(db_session, actor=admin_user, apply=False)
    assert [p for p, _ in planned] == [patient.id]
    assert await _doctors_of(db_session, patient.id) == set()


async def test_the_one_off_script_assigns_each_doctorless_patient_once(
    db_session, patient, admin_user
):
    quiet = await _doctor(db_session, "quiet")
    provisional = Patient(mrn="MRN-PROV01", name="Prov", is_provisional=True)
    db_session.add(provisional)
    await db_session.commit()

    done = await assign_missing_doctors.run(db_session, actor=admin_user, apply=True)

    assert done == [(patient.id, quiet.id)]
    assert await _doctors_of(db_session, patient.id) == {quiet.id}
    assert await _doctors_of(db_session, provisional.id) == set()
    assert await assign_missing_doctors.run(db_session, actor=admin_user, apply=True) == []
