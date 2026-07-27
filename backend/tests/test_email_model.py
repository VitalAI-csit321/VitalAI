from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models.email import Email


@pytest.mark.asyncio
async def test_email_persists_and_links_to_case(db_session, patient):
    from app.models.case import IntakeCase, IntakeStatus

    case = IntakeCase(
        patient_id=patient.id,
        contact_reason="Prescription renewal request",
        contact_channel="email",
        status=IntakeStatus.RECEIVED,
    )
    db_session.add(case)
    await db_session.flush()

    email = Email(
        case_id=case.id,
        sender="patient@example.com",
        recipient="clinic@example.com",
        subject="Need my prescription renewed",
        body="Hi, can you renew my blood pressure medication?",
        received_at=datetime.now(UTC),
    )
    db_session.add(email)
    await db_session.commit()

    result = await db_session.execute(select(Email).where(Email.case_id == case.id))
    stored = result.scalar_one()
    assert stored.sender == "patient@example.com"
    assert stored.subject == "Need my prescription renewed"
