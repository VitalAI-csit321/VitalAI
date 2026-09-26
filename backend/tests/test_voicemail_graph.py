"""Voicemail on the agent graph (voicemail spec §8). Flag on throughout."""

import re
from datetime import date

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.models.assignment import DoctorPatientAssignment
from app.models.call import CallStatus
from app.models.case import IntakeCase
from app.models.patient import Patient, PatientStatus
from app.models.task import Task
from app.services import voicemail_service
from tests.voicemail_fakes import FakeClassifier, FakeStorage, fake_transcript

DOB = date(1985, 7, 3)


@pytest.fixture(autouse=True)
def setup(monkeypatch, detached_sessionmaker, agent_saver):
    monkeypatch.setattr(settings, "agentic_pipeline_enabled", True)
    monkeypatch.setattr(settings, "clinic_open_hour", 8)
    monkeypatch.setattr(settings, "clinic_close_hour", 18)
    monkeypatch.setattr(settings, "clinic_timezone", "Australia/Sydney")
    monkeypatch.setattr(settings, "default_appointment_duration_minutes", 30)
    monkeypatch.setattr(voicemail_service, "AsyncSessionLocal", detached_sessionmaker)
    monkeypatch.setattr(
        voicemail_service, "get_llm", lambda: FakeClassifier("general_administrative")
    )
    fake_transcript(monkeypatch, "Hi, it's Jane, please call me back.")
    FakeStorage().install(monkeypatch)


async def _patient(db, name="Jane Smith", phone="0412 345 678", dob=DOB, **extra) -> Patient:
    count = (await db.execute(select(func.count()).select_from(Patient))).scalar_one()
    patient = Patient(
        mrn=f"MRN-VM{count:04d}",
        name=name,
        phone=phone,
        dob=dob,
        status=extra.pop("status", PatientStatus.ACTIVE),
        **extra,
    )
    db.add(patient)
    await db.commit()
    return patient


async def _voicemail(db, *, from_number="+61412345678", dob=DOB, intent="results", urgent=False):
    actor = await voicemail_service.intake_actor(db)
    call = await voicemail_service.create_voicemail(
        db,
        from_number=from_number,
        actor=actor,
        status=CallStatus.RECEIVED,
        keypad_dob=dob,
        keypad_intent=intent,
        urgent_pressed=urgent,
    )
    await voicemail_service.store_audio(db, call, b"RIFF", ".wav")
    await voicemail_service.process(call.id)
    task = (await db.execute(select(Task).where(Task.call_id == call.id))).scalar_one()
    await db.refresh(task)
    return call, task


async def test_unique_phone_and_dob_names_a_probable_patient(db_session):
    await _patient(db_session)
    call, task = await _voicemail(db_session)
    script = task.handover_context
    assert "Call back +61412345678." in script
    assert "Probable patient: Jane Smith" in script
    assert "Confirm the caller's full name and date of birth" in script
    assert "Offer" not in script
    # Probable only: the case is never linked (spec global constraint).
    case = await db_session.get(IntakeCase, call.case_id)
    assert case.patient_id is None


async def test_shared_phone_and_dob_matches_nobody(db_session):
    await _patient(db_session, name="Twin One")
    await _patient(db_session, name="Twin Two")
    _, task = await _voicemail(db_session)
    assert "Caller not identified" in task.handover_context
    assert "Twin" not in task.handover_context


async def test_no_keypad_dob_matches_nobody(db_session):
    await _patient(db_session)
    _, task = await _voicemail(db_session, dob=None)
    assert "Caller not identified" in task.handover_context


async def test_withheld_number_never_matches(db_session):
    await _patient(db_session)
    _, task = await _voicemail(db_session, from_number="anonymous")
    assert "Caller ID withheld" in task.handover_context
    assert "Jane" not in task.handover_context.split("They said")[0]


async def test_appointment_offers_slots_from_the_patients_doctor(
    db_session, doctor_user, admin_user
):
    patient = await _patient(db_session)
    db_session.add(
        DoctorPatientAssignment(
            doctor_id=doctor_user.id, patient_id=patient.id, assigned_by=admin_user.id
        )
    )
    await db_session.commit()
    _, task = await _voicemail(db_session, intent="appointment")
    assert re.search(
        r"Offer .+: (Monday|Tuesday|Wednesday|Thursday|Friday) \d+ \w+ at \d+:\d\d(am|pm)",
        task.handover_context,
    ), task.handover_context


async def test_appointment_without_a_doctor_says_book_by_hand(db_session):
    await _patient(db_session)
    _, task = await _voicemail(db_session, intent="appointment")
    assert "book by hand" in task.handover_context


async def test_provisional_patient_is_named_but_not_booked(db_session, doctor_user, admin_user):
    patient = await _patient(db_session, is_provisional=True)
    db_session.add(
        DoctorPatientAssignment(
            doctor_id=doctor_user.id, patient_id=patient.id, assigned_by=admin_user.id
        )
    )
    await db_session.commit()
    _, task = await _voicemail(db_session, intent="appointment")
    assert "Probable patient: Jane Smith" in task.handover_context
    assert "Offer" not in task.handover_context


async def test_urgent_voicemail_keeps_its_urgent_script(db_session):
    await _patient(db_session)
    _, task = await _voicemail(db_session, urgent=True)
    assert task.handover_context.startswith("URGENT voicemail")
    assert "Probable patient" not in task.handover_context  # graph ended before identity


async def test_complaint_gets_a_callback_script(db_session, monkeypatch):
    monkeypatch.setattr(
        voicemail_service, "get_llm", lambda: FakeClassifier("complaint_escalation")
    )
    await _patient(db_session)
    _, task = await _voicemail(db_session, intent=None)
    assert task.handover_context is not None
    assert "Call back +61412345678." in task.handover_context
