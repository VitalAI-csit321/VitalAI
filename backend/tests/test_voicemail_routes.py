from uuid import UUID

import pytest
from sqlalchemy import select

from app.config import settings
from app.models.call import Call, CallStatus
from app.models.task import Task, TaskCategory, TaskPriority
from app.services import voicemail_service
from tests.voicemail_fakes import FakeClassifier, FakeStorage, fake_transcript

URL = "/api/v1/voicemails/simulate"


@pytest.fixture(autouse=True)
def setup(monkeypatch, detached_sessionmaker):
    monkeypatch.setattr(settings, "agentic_pipeline_enabled", False)
    monkeypatch.setattr(voicemail_service, "AsyncSessionLocal", detached_sessionmaker)
    monkeypatch.setattr(
        voicemail_service, "get_llm", lambda: FakeClassifier("general_administrative")
    )
    fake_transcript(monkeypatch, "Could someone call me about my appointment?")
    return FakeStorage().install(monkeypatch)


def _form(**overrides):
    data = {
        "from_number": "+61412345678",
        "dob_digits": "03071985",
        "intent_digit": "1",
        "urgent": "false",
    }
    data.update(overrides)
    return data


async def test_simulate_creates_and_processes(client, operator_headers, db_session, setup):
    response = await client.post(
        URL,
        data=_form(),
        files={"audio": ("vm.wav", b"RIFF", "audio/wav")},
        headers=operator_headers,
    )
    assert response.status_code == 202
    call = await db_session.get(Call, UUID(response.json()["call_id"]))
    await db_session.refresh(call)
    assert call.status == CallStatus.PROCESSED  # the background task ran
    assert call.keypad_intent == "appointment"
    assert call.keypad_dob.isoformat() == "1985-07-03"
    assert f"voicemail/{call.id}.wav" in setup.objects
    task = (await db_session.execute(select(Task).where(Task.call_id == call.id))).scalar_one()
    assert task.category == TaskCategory.APPOINTMENT_REQUEST


async def test_simulate_urgent(client, operator_headers, db_session):
    response = await client.post(
        URL,
        data=_form(urgent="true"),
        files={"audio": ("vm.mp3", b"ID3", "audio/mpeg")},
        headers=operator_headers,
    )
    call = await db_session.get(Call, UUID(response.json()["call_id"]))
    task = (await db_session.execute(select(Task).where(Task.call_id == call.id))).scalar_one()
    assert task.priority == TaskPriority.URGENT


async def test_simulate_rejects_unknown_audio_type(client, operator_headers):
    response = await client.post(
        URL,
        data=_form(),
        files={"audio": ("vm.exe", b"MZ", "application/octet-stream")},
        headers=operator_headers,
    )
    assert response.status_code == 415


async def test_simulate_rejects_empty_audio(client, operator_headers):
    response = await client.post(
        URL, data=_form(), files={"audio": ("vm.wav", b"", "audio/wav")}, headers=operator_headers
    )
    assert response.status_code == 422


async def test_front_desk_cannot_simulate(client, front_desk_headers):
    response = await client.post(
        URL,
        data=_form(),
        files={"audio": ("vm.wav", b"RIFF", "audio/wav")},
        headers=front_desk_headers,
    )
    assert response.status_code == 403
