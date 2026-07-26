import pytest

from app.llm.output_guardrail import OutputBlockedError, check_output


@pytest.mark.asyncio
async def test_check_output_blocks_diagnosis_language(db_session, front_desk_user, patient):
    from app.models.case import IntakeCase, IntakeStatus

    case = IntakeCase(
        patient_id=patient.id,
        contact_reason="test",
        contact_channel="email",
        status=IntakeStatus.RECEIVED,
    )
    db_session.add(case)
    await db_session.flush()

    with pytest.raises(OutputBlockedError) as exc_info:
        await check_output(
            db_session,
            "Based on your symptoms, this looks like a diagnosis worth discussing further.",
            actor=front_desk_user,
            case_id=case.id,
        )
    assert exc_info.value.matched_term == "diagnosis"


@pytest.mark.asyncio
async def test_check_output_allows_clean_draft(db_session, front_desk_user, patient):
    from app.models.case import IntakeCase, IntakeStatus

    case = IntakeCase(
        patient_id=patient.id,
        contact_reason="test",
        contact_channel="email",
        status=IntakeStatus.RECEIVED,
    )
    db_session.add(case)
    await db_session.flush()

    await check_output(
        db_session,
        "Thank you for your message. We have received your appointment request and will confirm shortly.",
        actor=front_desk_user,
        case_id=case.id,
    )
    # No exception raised = pass.


@pytest.mark.asyncio
async def test_check_output_records_audit_event_on_block(db_session, front_desk_user, patient):
    from sqlalchemy import select

    from app.models.audit import AuditEvent
    from app.models.case import IntakeCase, IntakeStatus

    case = IntakeCase(
        patient_id=patient.id,
        contact_reason="test",
        contact_channel="email",
        status=IntakeStatus.RECEIVED,
    )
    db_session.add(case)
    await db_session.flush()

    with pytest.raises(OutputBlockedError):
        await check_output(
            db_session, "Your prescription is ready.", actor=front_desk_user, case_id=case.id
        )

    result = await db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "governance.output_blocked")
    )
    event = result.scalars().first()
    assert event is not None
    assert event.details["matched_term"] == "prescription"
