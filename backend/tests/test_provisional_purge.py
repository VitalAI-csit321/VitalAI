"""Purge after 90 days = anonymise in place (build spec §9.1).

Never a DELETE: no FK referencing patients.id declares an ondelete, and rows
referenced from audit details must stay where the hash chain expects them.
The originating Email and IntakeCase are deliberately kept, so "no personal
data retained" is not true: the patient record is anonymised, the
correspondence is not.
"""

import asyncio
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

from app.config import settings
from app.models.appointment import Appointment, AppointmentStatus
from app.models.audit import AuditEvent
from app.models.case import IntakeCase
from app.models.email import Email
from app.models.patient import PROFILE_FIELDS, PatientStatus
from app.services import audit_service, patient_service, provisional_purge
from app.services.booking_service import format_slot
from tests.agent_fakes import seed_email


@pytest.fixture
async def purgeable(db_session, admin_user):
    """A provisional patient, their case and their email, all old enough."""
    email, _ = await seed_email(db_session, sender="riley@example.com")
    patient = await patient_service.create_provisional_patient(
        db_session,
        case_id=email.case_id,
        name="Riley Newcomer",
        email="riley@example.com",
        phone="0412 345 678",
        dob=date(1992, 5, 17),
        actor=admin_user,
    )
    patient.address = "1 Test Street"
    patient.created_at = datetime.now(UTC) - timedelta(
        days=settings.provisional_patient_ttl_days + 1
    )
    await db_session.commit()
    return patient, email


async def test_purge_anonymises_and_keeps_the_correspondence(db_session, admin_user, purgeable):
    patient, email = purgeable

    purged = await provisional_purge.purge_due(db_session, admin_user)

    assert purged == [patient.id]
    await db_session.refresh(patient)
    assert patient.name == "[purged]"
    assert patient.dob is None and patient.gender is None
    assert all(getattr(patient, f) is None for f in PROFILE_FIELDS)
    assert patient.status == PatientStatus.INACTIVE
    assert patient.is_provisional is True
    assert patient.purged_at is not None
    assert patient.mrn  # the opaque handle stays
    case = await db_session.get(IntakeCase, email.case_id)
    await db_session.refresh(case)
    assert case is not None and case.patient_name is None
    assert await db_session.get(Email, email.id) is not None
    events = (await db_session.execute(select(AuditEvent))).scalars().all()
    assert [e for e in events if e.action == "patient.purged"]
    assert (await audit_service.verify_chain(db_session))["valid"] is True


async def test_a_second_run_is_a_no_op(db_session, admin_user, purgeable):
    patient, _ = purgeable
    await provisional_purge.purge_due(db_session, admin_user)
    await db_session.refresh(patient)
    stamp = patient.purged_at

    assert await provisional_purge.purge_due(db_session, admin_user) == []
    await db_session.refresh(patient)
    assert patient.purged_at == stamp


async def test_recent_and_promoted_patients_are_left_alone(db_session, admin_user, purgeable):
    old, email = purgeable
    recent = await patient_service.create_provisional_patient(
        db_session,
        case_id=email.case_id,
        name="Sam Recent",
        email="sam@example.com",
        phone=None,
        dob=None,
        actor=admin_user,
    )
    old.is_provisional = False  # promoted before the deadline
    await db_session.commit()

    assert await provisional_purge.purge_due(db_session, admin_user) == []
    await db_session.refresh(old)
    await db_session.refresh(recent)
    assert old.name == "Riley Newcomer"
    assert recent.name == "Sam Recent"


async def test_the_sweep_only_starts_with_the_flag_on(monkeypatch):
    from app import main

    started = []

    async def fake_run_purge():
        started.append("purge")

    async def no_hydrate(db):
        return None

    monkeypatch.setattr("app.services.settings_service.hydrate", no_hydrate)
    monkeypatch.setattr(settings, "outlook_enabled", False)
    monkeypatch.setattr("app.services.provisional_purge.run_purge", fake_run_purge)

    monkeypatch.setattr(settings, "agentic_pipeline_enabled", False)
    async with main.lifespan(main.app):
        await asyncio.sleep(0)  # let any created task actually start
    assert started == []

    monkeypatch.setattr(settings, "agentic_pipeline_enabled", True)
    monkeypatch.setattr("app.agents.checkpointer.open_checkpointer", _fake_checkpointer)
    async with main.lifespan(main.app):
        await asyncio.sleep(0)
    assert started == ["purge"]


def _fake_checkpointer():
    from contextlib import asynccontextmanager

    class FakeSaver:
        async def setup(self):
            return None

    @asynccontextmanager
    async def cm():
        yield FakeSaver()

    return cm()


async def test_one_bad_cycle_does_not_kill_the_loop(monkeypatch):
    """Same policy as the Outlook poller: nothing restarts this loop."""
    calls = []

    async def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database hiccup")
        raise asyncio.CancelledError

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(provisional_purge, "purge_once", flaky)
    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    with pytest.raises(asyncio.CancelledError):
        await provisional_purge.run_purge()
    assert len(calls) == 2


@pytest.fixture
def mail(monkeypatch):
    monkeypatch.setattr(settings, "outlook_enabled", True)
    monkeypatch.setattr("app.services.outlook_auth.get_access_token", AsyncMock(return_value="t"))
    sent = AsyncMock(return_value=None)
    monkeypatch.setattr("app.services.outlook_client.send_mail", sent)
    return sent


async def _appointment(db, case_id, doctor, *, days: int, status=AppointmentStatus.CONFIRMED):
    appointment = Appointment(
        case_id=case_id,
        doctor_id=doctor.id,
        time_slot=(datetime.now(UTC) + timedelta(days=days)).replace(
            minute=0, second=0, microsecond=0
        ),
        status=status,
        reason="Sore knee",
        internal_notes="Staff note",
    )
    db.add(appointment)
    await db.commit()
    return appointment


async def _actions(db) -> list[AuditEvent]:
    return (await db.execute(select(AuditEvent))).scalars().all()


async def test_an_upcoming_appointment_is_cancelled_and_the_patient_told_first(
    db_session, admin_user, doctor_user, purgeable, mail
):
    patient, email = purgeable
    upcoming = await _appointment(db_session, email.case_id, doctor_user, days=10)

    await provisional_purge.purge_due(db_session, admin_user)

    await db_session.refresh(upcoming)
    assert upcoming.status == AppointmentStatus.CANCELLED
    assert upcoming.reason is None and upcoming.internal_notes is None
    mail.assert_awaited_once()
    _, to_address, subject, body = mail.await_args.args
    assert to_address == "riley@example.com"  # sent before the address was blanked
    assert subject == provisional_purge.NOTICE_SUBJECT
    assert format_slot(upcoming.time_slot) in body
    assert "registration with the clinic was not completed" in body
    assert "contact the clinic" in body
    assert "Riley" not in body
    events = await _actions(db_session)
    assert [e for e in events if e.action == "appointment.purge_notice_sent"]
    cancelled = [e for e in events if e.action == "appointment.cancelled"]
    assert cancelled[0].details["cancel_reason"] == "patient record purged"
    assert (await audit_service.verify_chain(db_session))["valid"] is True


async def test_a_past_appointment_keeps_its_status_but_loses_its_notes(
    db_session, admin_user, doctor_user, purgeable, mail
):
    _, email = purgeable
    past = await _appointment(db_session, email.case_id, doctor_user, days=-10)

    await provisional_purge.purge_due(db_session, admin_user)

    await db_session.refresh(past)
    assert past.status == AppointmentStatus.CONFIRMED
    assert past.reason is None and past.internal_notes is None
    mail.assert_not_awaited()


async def test_no_address_means_no_notice_but_still_cancelled(
    db_session, admin_user, doctor_user, purgeable, mail
):
    patient, email = purgeable
    patient.email = None
    await db_session.commit()
    upcoming = await _appointment(db_session, email.case_id, doctor_user, days=10)

    await provisional_purge.purge_due(db_session, admin_user)

    await db_session.refresh(upcoming)
    assert upcoming.status == AppointmentStatus.CANCELLED
    mail.assert_not_awaited()


async def test_a_failed_notice_still_purges_and_is_recorded(
    db_session, admin_user, doctor_user, purgeable, mail
):
    patient, email = purgeable
    upcoming = await _appointment(db_session, email.case_id, doctor_user, days=10)
    mail.side_effect = httpx.HTTPError("mailbox unavailable")

    await provisional_purge.purge_due(db_session, admin_user)

    await db_session.refresh(patient)
    await db_session.refresh(upcoming)
    assert patient.purged_at is not None
    assert upcoming.status == AppointmentStatus.CANCELLED
    (failed,) = [
        e for e in await _actions(db_session) if e.action == "appointment.purge_notice_failed"
    ]
    assert failed.details["error"] == "EmailSendError"
    assert "riley" not in str(failed.details)


async def test_the_cancelled_slot_can_be_booked_again(
    db_session, admin_user, doctor_user, purgeable, mail
):
    if db_session.bind.dialect.name != "postgresql":
        pytest.skip("excl_doctor_overlap exists on Postgres only")
    _, email = purgeable
    upcoming = await _appointment(db_session, email.case_id, doctor_user, days=10)

    await provisional_purge.purge_due(db_session, admin_user)
    db_session.add(
        Appointment(
            case_id=email.case_id,
            doctor_id=doctor_user.id,
            time_slot=upcoming.time_slot,
            status=AppointmentStatus.CONFIRMED,
        )
    )
    await db_session.commit()  # raises IntegrityError if the slot were still held
