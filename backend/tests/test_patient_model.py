from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case import IntakeCase, IntakeStatus
from app.models.patient import Gender, Patient, PatientStatus


async def test_patient_persists_with_defaults(db_session: AsyncSession):
    patient = Patient(
        mrn="MRN-00000001",
        name="Ada Lovelace",
        dob=date(1990, 1, 1),
        gender=Gender.FEMALE,
        status=PatientStatus.PENDING,
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)

    assert patient.id is not None
    assert patient.status == PatientStatus.PENDING
    assert patient.gender == Gender.FEMALE


async def test_patient_mrn_must_be_unique(db_session: AsyncSession):
    db_session.add(
        Patient(
            mrn="MRN-DUP",
            name="A",
            dob=date(1990, 1, 1),
            gender=Gender.MALE,
            status=PatientStatus.ACTIVE,
        )
    )
    await db_session.commit()

    db_session.add(
        Patient(
            mrn="MRN-DUP",
            name="B",
            dob=date(1991, 1, 1),
            gender=Gender.MALE,
            status=PatientStatus.ACTIVE,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_intake_case_patient_id_is_nullable(db_session: AsyncSession):
    case = IntakeCase(
        contact_reason="checkup",
        contact_channel="phone",
        status=IntakeStatus.RECEIVED,
    )
    db_session.add(case)
    await db_session.commit()
    await db_session.refresh(case)

    assert case.patient_id is None
    assert case.patient_name is None


async def test_intake_case_links_to_patient(db_session: AsyncSession):
    patient = Patient(
        mrn="MRN-LINK01",
        name="Linked Patient",
        dob=date(1985, 5, 5),
        gender=Gender.NON_BINARY,
        status=PatientStatus.ACTIVE,
    )
    db_session.add(patient)
    await db_session.flush()

    case = IntakeCase(
        patient_id=patient.id,
        contact_reason="checkup",
        contact_channel="phone",
        status=IntakeStatus.RECEIVED,
    )
    db_session.add(case)
    await db_session.commit()
    await db_session.refresh(case)

    assert case.patient_id == patient.id
