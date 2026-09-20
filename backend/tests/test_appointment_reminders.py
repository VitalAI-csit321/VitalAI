"""Appointment reminders, 24 hours before (build spec §16).

Not an agent: no model, no critic, no approval. This is the one outbound
path in the system that reaches a patient with nobody clicking, so what it
selects, what it refuses to say, and the fact that it says it exactly once
are all load-bearing.

Outlook is mocked everywhere and every address is example.com.
"""

import asyncio
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import select

from app.config import settings
from app.models.appointment import AppointmentStatus
from app.models.audit import AuditEvent
from app.models.case import IntakeCase
from app.models.patient import Gender, Patient, PatientStatus
from app.models.user import User, UserRole
from app.schemas.appointment import AppointmentUpdate
from app.services import appointment_reminders, appointment_service
from app.services.outlook_auth import OutlookAuthRequiredError

SYDNEY = ZoneInfo("Australia/Sydney")

# Values that would be plainly visible in the rendered body if either field
# ever leaked into it.
REASON_SENTINEL = "REASON MUST NOT APPEAR IN EMAIL"
NOTES_SENTINEL = "INTERNAL NOTES MUST NOT APPEAR IN EMAIL"


@pytest.fixture(autouse=True)
def clinic(monkeypatch):
    monkeypatch.setattr(settings, "clinic_timezone", "Australia/Sydney")
    monkeypatch.setattr(settings, "outlook_enabled", True)
    monkeypatch.setattr("app.services.outlook_auth.get_access_token", AsyncMock(return_value="t"))


@pytest.fixture
def sends(monkeypatch):
    mock = AsyncMock(return_value=None)
    monkeypatch.setattr("app.services.outlook_client.send_mail", mock)
    return mock


def _user(role: UserRole) -> User:
    return User(
        email=f"{role.value}-{uuid4().hex[:8]}@example.com",
        hashed_password="h",
        full_name="Test Staff",
        role=role,
    )


async def _patient(db, **extra) -> Patient:
    patient = Patient(
        mrn=f"MRN-{uuid4().hex[:8].upper()}",
        name=extra.pop("name", "Jane Smith"),
        dob=date(1985, 6, 1),
        gender=Gender.FEMALE,
        status=PatientStatus.ACTIVE,
        email=extra.pop("email", "jane@example.com"),
        **extra,
    )
    db.add(patient)
    await db.commit()
    return patient


async def _appointment(db, actor, doctor, patient, *, hours=23, **extra):
    case = IntakeCase(
        patient_id=patient.id if patient else None,
        patient_name=patient.name if patient else None,
        contact_reason="Checkup",
        contact_channel="email",
    )
    db.add(case)
    await db.commit()
    return await appointment_service.book_appointment(
        db,
        doctor.id,
        case.id,
        datetime.now(UTC).replace(microsecond=0) + timedelta(hours=hours),
        actor,
        status=extra.pop("status", AppointmentStatus.CONFIRMED),
        location=extra.pop("location", "Main Clinic"),
        reason=extra.pop("reason", REASON_SENTINEL),
        internal_notes=extra.pop("internal_notes", NOTES_SENTINEL),
        **extra,
    )


@pytest.fixture
async def setup(db_session):
    """An actor, a doctor, and a patient who can be reached."""
    admin = _user(UserRole.ADMIN)
    doctor = _user(UserRole.DOCTOR)
    db_session.add_all([admin, doctor])
    await db_session.commit()
    patient = await _patient(db_session)
    return admin, doctor, patient


async def _sent_events(db, appointment_id) -> list[AuditEvent]:
    """Scoped to the appointment under test: the AGENT_XPROC worker commits
    audit rows a trigger makes undeletable, so a global count passes alone
    and fails in a full run."""
    rows = (await db.execute(select(AuditEvent))).scalars().all()
    return [
        e
        for e in rows
        if e.action == appointment_reminders.SENT_ACTION
        and e.details.get("appointment_id") == str(appointment_id)
    ]


async def test_a_confirmed_appointment_is_reminded_exactly_once(db_session, setup, sends):
    """Two consecutive cycles, one email. reminder_sent_at is the guard."""
    admin, doctor, patient = setup
    appointment = await _appointment(db_session, admin, doctor, patient)

    first = await appointment_reminders.send_due_reminders(db_session, admin)
    second = await appointment_reminders.send_due_reminders(db_session, admin)

    assert first == [appointment.id]
    assert second == []
    sends.assert_awaited_once()
    await db_session.refresh(appointment)
    assert appointment.reminder_sent_at is not None
    assert len(await _sent_events(db_session, appointment.id)) == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"status": AppointmentStatus.CANCELLED}, id="cancelled"),
        pytest.param({"status": AppointmentStatus.PENDING}, id="pending"),
        pytest.param({"status": AppointmentStatus.COMPLETED}, id="completed"),
        pytest.param({"notify_patient": False}, id="notify_patient_off"),
        pytest.param({"hours": -1}, id="already_started"),
        pytest.param({"hours": 30}, id="more_than_24h_out"),
    ],
)
async def test_the_window_and_the_flags_exclude_these(db_session, setup, sends, kwargs):
    admin, doctor, patient = setup
    await _appointment(db_session, admin, doctor, patient, **kwargs)

    assert await appointment_reminders.send_due_reminders(db_session, admin) == []
    sends.assert_not_awaited()


@pytest.mark.parametrize(
    "no_patient, after_booking",
    [
        pytest.param(True, {}, id="case_has_no_patient"),
        pytest.param(False, {"email": None}, id="patient_has_no_email"),
        # Applied after booking on purpose: book_appointment calls
        # assert_not_provisional, so a provisional patient cannot be booked at
        # all (§9). The guard exists for a patient who becomes provisional or
        # is purged after the booking was made, which is exactly the case
        # §16.4 says "should never fire, which is why it is worth a guard".
        pytest.param(False, {"is_provisional": True}, id="provisional_after_booking"),
        pytest.param(False, {"purged_at": datetime.now(UTC)}, id="purged_after_booking"),
    ],
)
async def test_an_unreachable_patient_is_skipped_and_audited_once(
    db_session, setup, sends, no_patient, after_booking
):
    """Never falls back to the inbound sender's address, and writes one
    aggregate event for the cycle rather than one per appointment."""
    admin, doctor, _ = setup
    patient = None if no_patient else await _patient(db_session)
    appointment = await _appointment(db_session, admin, doctor, patient)
    if patient is not None and after_booking:
        for field, value in after_booking.items():
            setattr(patient, field, value)
        await db_session.commit()

    assert await appointment_reminders.send_due_reminders(db_session, admin) == []

    sends.assert_not_awaited()
    await db_session.refresh(appointment)
    assert appointment.reminder_sent_at is None
    rows = (await db_session.execute(select(AuditEvent))).scalars().all()
    skipped = [
        e
        for e in rows
        if e.action == appointment_reminders.SKIPPED_ACTION
        and str(appointment.id) in e.details["appointment_ids"]
    ]
    assert len(skipped) == 1
    assert skipped[0].details["count"] == 1


async def test_nothing_due_writes_no_audit_event_at_all(db_session, setup, sends):
    admin, _, _ = setup
    before = len((await db_session.execute(select(AuditEvent))).scalars().all())

    assert await appointment_reminders.send_due_reminders(db_session, admin) == []

    sends.assert_not_awaited()
    after = len((await db_session.execute(select(AuditEvent))).scalars().all())
    assert after == before


async def test_rescheduling_after_a_reminder_reminds_the_new_slot(db_session, setup, sends):
    admin, doctor, patient = setup
    appointment = await _appointment(db_session, admin, doctor, patient)
    assert await appointment_reminders.send_due_reminders(db_session, admin) == [appointment.id]

    await appointment_service.reschedule_appointment(
        db_session,
        appointment.id,
        datetime.now(UTC).replace(microsecond=0) + timedelta(hours=20),
        admin,
        scoped_doctor_id=None,
    )

    assert await appointment_reminders.send_due_reminders(db_session, admin) == [appointment.id]
    assert sends.await_count == 2


async def test_a_patch_that_moves_the_time_reminds_the_new_slot(db_session, setup, sends):
    admin, doctor, patient = setup
    appointment = await _appointment(db_session, admin, doctor, patient)
    assert await appointment_reminders.send_due_reminders(db_session, admin) == [appointment.id]

    await appointment_service.update_appointment(
        db_session,
        appointment.id,
        AppointmentUpdate(time_slot=datetime.now(UTC).replace(microsecond=0) + timedelta(hours=19)),
        admin,
        scoped_doctor_id=None,
    )

    assert await appointment_reminders.send_due_reminders(db_session, admin) == [appointment.id]
    assert sends.await_count == 2


async def test_the_body_carries_no_staff_notes_and_shows_clinic_local_time(
    db_session, setup, sends
):
    """The two free-text fields that can hold clinical detail never reach the
    patient, and the time is Sydney's, not UTC's."""
    admin, doctor, patient = setup
    appointment = await _appointment(db_session, admin, doctor, patient)

    await appointment_reminders.send_due_reminders(db_session, admin)

    (_, _, _, body) = sends.await_args.args
    assert REASON_SENTINEL not in body
    assert NOTES_SENTINEL not in body
    assert appointment.reason == REASON_SENTINEL  # the row still holds them
    assert appointment.internal_notes == NOTES_SENTINEL

    local = appointment.time_slot.astimezone(SYDNEY)
    hour = local.hour % 12 or 12
    meridiem = "am" if local.hour < 12 else "pm"
    assert f"{hour}:{local:%M}{meridiem}" in body
    assert f"{local:%A}" in body
    assert appointment.reference_code in body
    assert "Main Clinic" in body
    assert "Hi Jane," in body


async def test_a_failed_send_leaves_the_guard_null_and_retries(db_session, setup, monkeypatch):
    admin, doctor, patient = setup
    appointment = await _appointment(db_session, admin, doctor, patient)
    failing = AsyncMock(side_effect=RuntimeError("graph is down"))
    monkeypatch.setattr("app.services.outlook_client.send_mail", failing)

    assert await appointment_reminders.send_due_reminders(db_session, admin) == []
    await db_session.refresh(appointment)
    assert appointment.reminder_sent_at is None

    working = AsyncMock(return_value=None)
    monkeypatch.setattr("app.services.outlook_client.send_mail", working)
    assert await appointment_reminders.send_due_reminders(db_session, admin) == [appointment.id]
    working.assert_awaited_once()


async def test_no_signed_in_mailbox_skips_the_whole_cycle(db_session, setup, monkeypatch):
    """One failure for the mailbox, not one per appointment."""
    admin, doctor, patient = setup
    other = await _patient(db_session, name="Sam Other", email="sam@example.com")
    await _appointment(db_session, admin, doctor, patient)
    # A different hour, because Postgres enforces excl_doctor_overlap
    # (migration 0026) and one doctor cannot hold two appointments in the same
    # slot. Both are still inside the 24 hour window, which is what this test
    # needs. SQLite has no such constraint, so the clash only shows on the
    # Postgres track.
    await _appointment(db_session, admin, doctor, other, hours=22)
    monkeypatch.setattr(
        "app.services.outlook_auth.get_access_token",
        AsyncMock(side_effect=OutlookAuthRequiredError("nobody signed in")),
    )

    assert await appointment_reminders.send_due_reminders(db_session, admin) == []

    rows = (await db_session.execute(select(AuditEvent))).scalars().all()
    assert [e for e in rows if e.action == appointment_reminders.SKIPPED_ACTION] == []


async def test_the_sweep_only_starts_with_its_own_flag_on(monkeypatch):
    """Not agentic_pipeline_enabled: a job that emails real patients must not
    start because someone turned the agent on."""
    from app import main

    started = []

    async def fake_run_reminders():
        started.append("reminders")

    async def no_hydrate(db):
        return None

    monkeypatch.setattr("app.services.settings_service.hydrate", no_hydrate)
    monkeypatch.setattr(settings, "outlook_enabled", False)
    monkeypatch.setattr(settings, "agentic_pipeline_enabled", False)
    monkeypatch.setattr("app.services.appointment_reminders.run_reminders", fake_run_reminders)

    monkeypatch.setattr(settings, "appointment_reminders_enabled", False)
    async with main.lifespan(main.app):
        # Without this the context manager cancels the task before the loop
        # body runs, and the test proves the opposite of what it claims.
        await asyncio.sleep(0)
    assert started == []

    monkeypatch.setattr(settings, "appointment_reminders_enabled", True)
    async with main.lifespan(main.app):
        await asyncio.sleep(0)
    assert started == ["reminders"]


async def test_shutdown_cancels_the_sweep(monkeypatch):
    """The task has to be in lifespan's cancel tuple. One left out of it
    keeps running against a closing event loop after shutdown, and the
    flag-on test above cannot see that because its fake returns immediately."""
    from app import main

    started = asyncio.Event()

    async def blocking_run_reminders():
        started.set()
        await asyncio.Event().wait()  # never finishes on its own

    async def no_hydrate(db):
        return None

    monkeypatch.setattr("app.services.settings_service.hydrate", no_hydrate)
    monkeypatch.setattr(settings, "outlook_enabled", False)
    monkeypatch.setattr(settings, "agentic_pipeline_enabled", False)
    monkeypatch.setattr(settings, "appointment_reminders_enabled", True)
    monkeypatch.setattr("app.services.appointment_reminders.run_reminders", blocking_run_reminders)

    before = set(asyncio.all_tasks())
    async with main.lifespan(main.app):
        await started.wait()
        running = [t for t in asyncio.all_tasks() - before if not t.done()]
        assert running, "the sweep task was never created"

    assert all(task.cancelled() or task.done() for task in running)


async def test_one_bad_cycle_does_not_kill_the_loop(monkeypatch):
    calls = []

    async def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database hiccup")
        raise asyncio.CancelledError

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(appointment_reminders, "remind_once", flaky)
    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    with pytest.raises(asyncio.CancelledError):
        await appointment_reminders.run_reminders()
    assert len(calls) == 2


async def test_a_failed_send_keeps_the_patient_address_out_of_the_logs(
    db_session, setup, monkeypatch, caplog
):
    """A patient's address is a contact detail, and logs are a lower trust
    surface than the row it came from. The failure is logged by appointment
    id and error type, never by recipient, and the audit event names no
    address either."""
    import logging

    admin, doctor, patient = setup
    appointment = await _appointment(db_session, admin, doctor, patient)
    monkeypatch.setattr(
        "app.services.outlook_client.send_mail",
        AsyncMock(side_effect=httpx.HTTPError("graph is down")),
    )

    with caplog.at_level(logging.DEBUG):
        assert await appointment_reminders.send_due_reminders(db_session, admin) == []

    assert patient.email not in caplog.text
    assert str(appointment.id) in caplog.text
    rows = (await db_session.execute(select(AuditEvent))).scalars().all()
    skipped = [
        e
        for e in rows
        if e.action == appointment_reminders.SKIPPED_ACTION
        and str(appointment.id) in e.details["appointment_ids"]
    ]
    assert len(skipped) == 1
    assert patient.email not in str(skipped[0].details)
