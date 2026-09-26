from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.call import Call, CallKind, CallStatus
from app.models.case import IntakeCase


async def _case(db) -> IntakeCase:
    case = IntakeCase(contact_reason="Voicemail", contact_channel="voicemail")
    db.add(case)
    await db.flush()
    return case


async def test_logged_call_defaults(db_session):
    case = await _case(db_session)
    call = Call(case_id=case.id, phone_number="0412345678")
    db_session.add(call)
    await db_session.commit()
    await db_session.refresh(call)
    assert call.kind == CallKind.LOGGED
    assert call.urgent_pressed is False
    assert call.twilio_deleted is None


async def test_voicemail_columns_round_trip(db_session):
    case = await _case(db_session)
    call = Call(
        case_id=case.id,
        phone_number="+61412345678",
        kind=CallKind.VOICEMAIL,
        status=CallStatus.RECORDING,
        twilio_call_sid="CA" + "0" * 32,
        keypad_dob=date(1985, 7, 3),
        keypad_intent="appointment",
        urgent_pressed=True,
        transcript_quality={"avg_logprob": -0.3, "low": False},
    )
    db_session.add(call)
    await db_session.commit()
    await db_session.refresh(call)
    assert call.status == CallStatus.RECORDING
    assert call.transcript_quality == {"avg_logprob": -0.3, "low": False}


async def test_call_sid_is_unique(db_session):
    case = await _case(db_session)
    sid = "CA" + "1" * 32
    db_session.add(Call(case_id=case.id, phone_number="1", twilio_call_sid=sid))
    await db_session.commit()
    db_session.add(Call(case_id=case.id, phone_number="2", twilio_call_sid=sid))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
