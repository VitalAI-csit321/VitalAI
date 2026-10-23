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

    # Scoped to this actor, not the first row globally: the shared dev database
    # already holds a governance.output_blocked event committed by an earlier
    # run, which db_session's rollback cannot remove, and .first() returns that
    # one instead. Same fix as commit f78d7cc.
    result = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.action == "governance.output_blocked",
            AuditEvent.actor_id == front_desk_user.id,
        )
    )
    event = result.scalars().first()
    assert event is not None
    assert event.details["matched_term"] == "prescription"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "draft",
    [
        "The clinic does not provide emergency care. In an emergency, call 000.",
        "The nearest emergency department is at Wollongong Hospital.",
        "Please bring your Medicare card and the name of an emergency contact.",
        "Dr Priya Menon offers Mental Health Treatment Plans.",
    ],
    ids=["000-direction", "emergency-department", "emergency-contact", "medicare-item-name"],
)
async def test_check_output_allows_the_clinics_own_safe_wording(db_session, front_desk_user, draft):
    """Deliberate choice: the word match threw away correct replies to
    "what do I do after hours?" because the clinic's own documents say "call
    000 in an emergency". The 000 direction, the emergency department, an
    emergency contact and the Medicare item's name are not the AI judging a
    patient's condition, which is what the terms exist to stop."""
    await check_output(db_session, draft, actor=front_desk_user, case_id=None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("draft", "term"),
    [
        ("From what you describe, this sounds like an emergency.", "emergency"),
        ("Your treatment plan should change.", "treatment plan"),
        # The 000 sentence excuses "emergency" only, not the rest of the list.
        ("This is an emergency, you must call 000.", "you must"),
    ],
    ids=["judging-urgency", "clinical-plan", "other-terms-in-a-000-sentence"],
)
async def test_check_output_still_blocks_restricted_wording_outside_the_safe_phrases(
    db_session, front_desk_user, draft, term
):
    with pytest.raises(OutputBlockedError) as exc_info:
        await check_output(db_session, draft, actor=front_desk_user, case_id=None)
    assert exc_info.value.matched_term == term
