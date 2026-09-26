import pytest
from sqlalchemy import select

from app.auth.permissions import PLAY_VOICEMAIL, effective_permissions
from app.models.audit import AuditEvent
from app.models.call import CallStatus
from app.models.user import User, UserRole
from app.services import voicemail_service
from tests.voicemail_fakes import FakeStorage


@pytest.fixture
def storage(monkeypatch):
    return FakeStorage().install(monkeypatch)


async def _voicemail(db, storage):
    actor = await voicemail_service.intake_actor(db)
    call = await voicemail_service.create_voicemail(
        db, from_number="+61412345678", actor=actor, status=CallStatus.PROCESSED
    )
    await voicemail_service.store_audio(db, call, b"RIFFDATA", ".wav")
    return call


@pytest.mark.parametrize("role", list(UserRole))
def test_every_role_can_play_voicemail(role):
    assert PLAY_VOICEMAIL in effective_permissions(User(role=role, email="x@y.z", full_name="x"))


@pytest.mark.parametrize(
    "headers", ["front_desk_headers", "operator_headers", "admin_headers", "doctor_headers"]
)
async def test_play_returns_audio_uncached_and_audited(
    client,
    db_session,
    storage,
    headers,
    front_desk_headers,
    operator_headers,
    admin_headers,
    doctor_headers,
):
    by_name = {
        "front_desk_headers": front_desk_headers,
        "operator_headers": operator_headers,
        "admin_headers": admin_headers,
        "doctor_headers": doctor_headers,
    }
    call = await _voicemail(db_session, storage)
    response = await client.get(f"/api/v1/calls/{call.id}/audio", headers=by_name[headers])
    assert response.status_code == 200
    assert response.content == b"RIFFDATA"
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.headers["cache-control"] == "no-store"
    actions = (
        (
            await db_session.execute(
                select(AuditEvent.action).where(AuditEvent.case_id == call.case_id)
            )
        )
        .scalars()
        .all()
    )
    assert "call.audio_played" in actions


async def test_purged_audio_is_gone(client, db_session, storage, admin_headers):
    call = await _voicemail(db_session, storage)
    call.audio_key = None
    await db_session.commit()
    response = await client.get(f"/api/v1/calls/{call.id}/audio", headers=admin_headers)
    assert response.status_code == 410


async def test_inbox_call_item_exposes_script_and_audio(
    client, db_session, storage, admin_headers, monkeypatch
):
    from tests.voicemail_fakes import FakeClassifier

    monkeypatch.setattr("app.services.inbox_service.get_llm", lambda: FakeClassifier())
    call = await _voicemail(db_session, storage)
    from app.models.task import Task, TaskItemStatus, TaskPriority, TaskSource

    db_session.add(
        Task(
            case_id=call.case_id,
            call_id=call.id,
            source=TaskSource.CALL,
            priority=TaskPriority.HIGH,
            status=TaskItemStatus.PENDING,
            handover_context="Call back +61412345678.",
        )
    )
    await db_session.commit()
    response = await client.get("/api/v1/inbox", headers=admin_headers)
    item = next(i for i in response.json()["items"] if i.get("callId") == str(call.id))
    assert item["hasAudio"] is True
    assert item["handoverContext"] == "Call back +61412345678."
