"""Provisional patients: identified from a message, not from a registration.

An agent that resolves "Jane from jane@example.com" to a new patient row has
no date of birth and no gender, which dob/gender NOT NULL made impossible to
record at all. The provisional marker is its own column rather than a
PatientStatus value, because patient_service recomputes status from profile
completeness on every edit and would silently overwrite it.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.patient import Patient, PatientStatus
from app.schemas.patient import PatientUpdate
from app.services import patient_service


async def test_patient_persists_without_dob_or_gender(db_session: AsyncSession):
    patient = Patient(mrn="MRN-PROV0001", name="Jane (unverified)", is_provisional=True)
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)

    assert patient.dob is None
    assert patient.gender is None
    assert patient.is_provisional is True
    assert patient.purged_at is None


async def test_is_provisional_defaults_to_false(db_session: AsyncSession):
    """Every existing patient, and every registered one, is not provisional."""
    from datetime import date

    from app.models.patient import Gender

    patient = Patient(
        mrn="MRN-PROV0002", name="Ada Lovelace", dob=date(1990, 1, 1), gender=Gender.FEMALE
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)

    assert patient.is_provisional is False


@pytest.mark.asyncio
async def test_editing_a_provisional_patient_does_not_clear_the_marker(
    db_session: AsyncSession, admin_user
):
    """The whole reason this is not a PatientStatus value: patient_service
    recomputes status on every edit, so a PROVISIONAL status would be gone
    after the first field update."""
    patient = Patient(mrn="MRN-PROV0003", name="Jane (unverified)", is_provisional=True)
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)

    await patient_service.update_patient(
        db_session, patient=patient, payload=PatientUpdate(phone="0400000000"), actor=admin_user
    )

    await db_session.refresh(patient)
    assert patient.is_provisional is True
    assert patient.status == PatientStatus.PENDING


async def test_purged_at_records_an_anonymised_row(db_session: AsyncSession):
    patient = Patient(
        mrn="MRN-PROV0004",
        name="Jane (unverified)",
        is_provisional=True,
        purged_at=datetime.now(UTC),
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)

    assert patient.purged_at is not None
