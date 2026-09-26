"""The Twilio voicemail line (voicemail spec §4, §11), driven by signed fake requests."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from twilio.request_validator import RequestValidator

from app.config import settings
from app.database import get_db
from app.models.audit import AuditEvent
from app.models.call import Call, CallStatus
from app.models.task import Task, TaskPriority
from app.routes import voice
from app.services import twilio_client, voicemail_service
from tests.voicemail_fakes import FakeClassifier, FakeStorage, fake_transcript

ACCOUNT = "AC" + "1" * 32
TOKEN = "test-auth-token"
BASE = "https://clinic.example"
CALL_SID = "CA" + "2" * 32
RECORDING_SID = "RE" + "3" * 32


@pytest.fixture
async def twilio(db_session, detached_sessionmaker, monkeypatch):
    monkeypatch.setattr(settings, "agentic_pipeline_enabled", False)
    monkeypatch.setattr(settings, "twilio_enabled", True)
    monkeypatch.setattr(settings, "twilio_account_sid", ACCOUNT)
    monkeypatch.setattr(settings, "twilio_auth_token", TOKEN)
    monkeypatch.setattr(settings, "twilio_webhook_base_url", BASE)
    monkeypatch.setattr(voicemail_service, "AsyncSessionLocal", detached_sessionmaker)
    monkeypatch.setattr(voicemail_service, "clinic_is_open", lambda now: True)
    monkeypatch.setattr(voicemail_service, "get_llm", lambda: FakeClassifier())
    fake_transcript(monkeypatch, "Please call me back about my results.")
    storage = FakeStorage().install(monkeypatch)
    downloads = AsyncMock(return_value=b"RIFFWAV")
    deletes = AsyncMock(return_value=True)
    monkeypatch.setattr(twilio_client, "download_recording", downloads)
    monkeypatch.setattr(twilio_client, "delete_recording", deletes)

    app = FastAPI()
    app.include_router(voice.router, prefix="/api/v1")

    async def override():
        yield db_session

    app.dependency_overrides[get_db] = override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.storage, client.downloads, client.deletes = storage, downloads, deletes
        yield client


async def _post(client, path, params, *, sign=True):
    full = {"AccountSid": ACCOUNT, "CallSid": CALL_SID, **params}
    url = f"{BASE}/api/v1/voice{path}"
    signature = RequestValidator(TOKEN).compute_signature(url, full) if sign else "forged"
    return await client.post(
        f"/api/v1/voice{path}", data=full, headers={"X-Twilio-Signature": signature}
    )


async def _call(db) -> Call:
    return (await db.execute(select(Call).where(Call.twilio_call_sid == CALL_SID))).scalar_one()


async def _through_menu(client, *, urgent="", dob="03071985", intent="2"):
    await _post(client, "/incoming", {"From": "+61412345678"})
    await _post(client, "/gather/urgent", {"Digits": urgent})
    await _post(client, "/gather/dob", {"Digits": dob})
    return await _post(client, "/gather/intent", {"Digits": intent})


async def test_forged_signature_is_rejected(twilio, db_session):
    response = await _post(twilio, "/incoming", {"From": "+61412345678"}, sign=False)
    assert response.status_code == 403
    assert (await db_session.execute(select(func.count()).select_from(Call))).scalar_one() == 0


async def test_wrong_account_is_rejected(twilio):
    params = {"From": "+61412345678", "AccountSid": "AC" + "9" * 32}
    url = f"{BASE}/api/v1/voice/incoming"
    full = {"CallSid": CALL_SID, **params}
    signature = RequestValidator(TOKEN).compute_signature(url, full)
    response = await twilio.post(
        "/api/v1/voice/incoming", data=full, headers={"X-Twilio-Signature": signature}
    )
    assert response.status_code == 403


async def test_closed_hangs_up_and_stores_no_number(twilio, db_session, monkeypatch):
    monkeypatch.setattr(voicemail_service, "clinic_is_open", lambda now: False)
    response = await _post(twilio, "/incoming", {"From": "+61412345678"})
    assert "<Hangup" in response.text
    assert "triple zero" in response.text
    assert (await db_session.execute(select(func.count()).select_from(Call))).scalar_one() == 0
    event = (
        await db_session.execute(
            select(AuditEvent).where(AuditEvent.action == "voicemail.after_hours_call")
        )
    ).scalar_one()
    assert "412345678" not in str(event.details)


async def test_menu_prompts_with_empty_result_actions(twilio):
    response = await _post(twilio, "/incoming", {"From": "+61412345678"})
    assert 'actionOnEmptyResult="true"' in response.text
    assert f'action="{BASE}/api/v1/voice/gather/urgent"' in response.text


async def test_full_menu_then_recording(twilio, db_session):
    response = await _through_menu(twilio, urgent="9")
    assert 'timeout="10"' in response.text
    assert 'maxLength="120"' in response.text
    assert f'recordingStatusCallback="{BASE}/api/v1/voice/recording"' in response.text
    call = await _call(db_session)
    assert call.urgent_pressed is True
    assert call.keypad_dob.isoformat() == "1985-07-03"
    assert call.keypad_intent == "results"
    assert call.status == CallStatus.RECORDING

    await _post(
        twilio, "/recording", {"RecordingSid": RECORDING_SID, "RecordingStatus": "completed"}
    )
    await db_session.refresh(call)
    assert call.status == CallStatus.PROCESSED
    assert call.twilio_deleted is True
    twilio.downloads.assert_awaited_once_with(RECORDING_SID)
    task = (await db_session.execute(select(Task).where(Task.call_id == call.id))).scalar_one()
    assert task.priority == TaskPriority.URGENT


async def test_skipped_dob_carries_on(twilio, db_session):
    response = await _through_menu(twilio, dob="")
    assert "<Record" in response.text
    assert (await _call(db_session)).keypad_dob is None


async def test_status_before_recording_callback_does_not_abandon(twilio, db_session):
    await _through_menu(twilio)
    await _post(twilio, "/status", {"CallStatus": "completed"})
    assert (await _call(db_session)).status == CallStatus.RECORDING
    await _post(
        twilio, "/recording", {"RecordingSid": RECORDING_SID, "RecordingStatus": "completed"}
    )
    assert (await _call(db_session)).status == CallStatus.PROCESSED


async def test_pressed_nine_then_hung_up_in_the_menu(twilio, db_session):
    await _post(twilio, "/incoming", {"From": "+61412345678"})
    await _post(twilio, "/gather/urgent", {"Digits": "9"})
    await _post(twilio, "/status", {"CallStatus": "completed"})
    call = await _call(db_session)
    assert call.status == CallStatus.ABANDONED
    task = (await db_session.execute(select(Task).where(Task.call_id == call.id))).scalar_one()
    assert task.priority == TaskPriority.URGENT


async def test_replayed_recording_callback_processes_once(twilio, db_session):
    await _through_menu(twilio)
    params = {"RecordingSid": RECORDING_SID, "RecordingStatus": "completed"}
    await _post(twilio, "/recording", params)
    await _post(twilio, "/recording", params)
    twilio.downloads.assert_awaited_once()
    call = await _call(db_session)
    tasks = (await db_session.execute(select(Task).where(Task.call_id == call.id))).scalars().all()
    assert len(tasks) == 1


async def test_download_failure_leaves_it_for_the_sweep(twilio, db_session):
    twilio.downloads.side_effect = RuntimeError("twilio down")
    await _through_menu(twilio)
    await _post(
        twilio, "/recording", {"RecordingSid": RECORDING_SID, "RecordingStatus": "completed"}
    )
    assert (await _call(db_session)).status == CallStatus.RECEIVED


def test_recording_url_refuses_anything_but_a_recording_sid():
    with pytest.raises(ValueError):
        twilio_client._recording_url("../../Calls/CA123", ".wav")
