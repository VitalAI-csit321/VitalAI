"""Voicemail on the agent graph (voicemail spec §8). Flag on throughout."""

import json
import re
from datetime import date

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.models.assignment import DoctorPatientAssignment
from app.models.call import CallStatus
from app.models.case import IntakeCase
from app.models.consent import ConsentRecord, ConsentStatus
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


async def test_a_probable_match_never_opens_a_case(db_session):
    # M4: a voicemail joins a case only once staff confirm the caller.
    from app.models.episode import Episode

    await _patient(db_session)
    _, task = await _voicemail(db_session, intent="results")
    assert task.category is not None and task.category.value == "results_enquiry"
    episodes = (await db_session.execute(select(func.count()).select_from(Episode))).scalar_one()
    assert episodes == 0


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


# Onboarding an unknown caller, the voicemail twin of the email §9.0 path.


class _FakeExtractor:
    """The identity-extraction model (email_service.get_llm)."""

    def __init__(self, name: str | None):
        self.name = name
        self.calls = 0

    async def ainvoke(self, prompt: str) -> str:
        self.calls += 1
        return json.dumps({"name": self.name, "dob": None, "phone": "0404 759 383"})


def _extractor(monkeypatch, name: str | None) -> _FakeExtractor:
    fake = _FakeExtractor(name)
    monkeypatch.setattr("app.services.email_service.get_llm", lambda: fake)
    return fake


async def _patients(db) -> list[Patient]:
    return list((await db.execute(select(Patient).order_by(Patient.created_at))).scalars())


async def test_unknown_caller_asking_to_book_becomes_a_provisional_patient(db_session, monkeypatch):
    _extractor(monkeypatch, "Jeremy")
    call, task = await _voicemail(db_session, intent="appointment")

    (patient,) = await _patients(db_session)
    assert patient.name == "Jeremy"
    assert patient.is_provisional is True
    assert patient.phone == "+61412345678"  # caller ID, never the spoken number
    assert patient.dob == DOB  # the keypad, never the transcript
    case = await db_session.get(IntakeCase, call.case_id)
    assert case.patient_id == patient.id
    consent = (
        await db_session.execute(select(ConsentRecord).where(ConsentRecord.case_id == call.case_id))
    ).scalar_one()
    assert consent.status == ConsentStatus.PENDING

    script = task.handover_context
    assert "New patient: provisional record created for Jeremy" in script
    assert "Caller not identified" not in script
    assert "Offer" not in script  # provisional patients are never booked


async def test_no_name_in_the_message_creates_nobody(db_session, monkeypatch):
    _extractor(monkeypatch, None)
    _, task = await _voicemail(db_session, intent="appointment")
    assert await _patients(db_session) == []
    assert "Caller not identified" in task.handover_context


async def test_unreliable_transcript_is_not_mined_for_a_name(db_session, monkeypatch):
    extractor = _extractor(monkeypatch, "Jeremy")
    fake_transcript(monkeypatch, "mumble", low=True)
    _, task = await _voicemail(db_session, intent="appointment")
    assert extractor.calls == 0
    assert await _patients(db_session) == []
    assert "Caller not identified" in task.handover_context


async def test_withheld_caller_is_not_onboarded(db_session, monkeypatch):
    _extractor(monkeypatch, "Jeremy")
    await _voicemail(db_session, from_number="anonymous", intent="appointment")
    assert await _patients(db_session) == []


async def test_other_intents_are_not_onboarded(db_session, monkeypatch):
    extractor = _extractor(monkeypatch, "Jeremy")
    await _voicemail(db_session, intent="results")
    assert extractor.calls == 0
    assert await _patients(db_session) == []


async def test_repeat_caller_reuses_their_provisional_record(db_session, monkeypatch):
    _extractor(monkeypatch, "Jeremy")
    await _voicemail(db_session, intent="appointment", dob=None)
    _, task = await _voicemail(db_session, from_number="0412345678", intent="appointment", dob=None)

    (patient,) = await _patients(db_session)
    assert patient.is_provisional is True
    assert "Probable new patient: Jeremy" in task.handover_context
    assert "same caller ID" in task.handover_context
