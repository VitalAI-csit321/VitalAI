import pytest

from app.config import settings
from app.services import settings_service
from app.services.settings_service import SettingsValidationError


@pytest.fixture(autouse=True)
def _restore_settings_singleton():
    """set_settings() mutates the process-wide `settings` singleton by design
    (see settings_service's ponytail note); without this, a write here leaks
    into every test that runs afterward in the same pytest session."""
    snapshot = {key: getattr(settings, key) for key in settings_service.SETTINGS_REGISTRY}
    yield
    for key, value in snapshot.items():
        setattr(settings, key, value)


@pytest.mark.asyncio
async def test_unknown_key_is_rejected(db_session, admin_user):
    with pytest.raises(SettingsValidationError):
        await settings_service.set_settings(db_session, {"not_a_real_key": 1}, admin_user)


@pytest.mark.asyncio
async def test_value_outside_declared_range_is_rejected(db_session, admin_user):
    with pytest.raises(SettingsValidationError):
        await settings_service.set_settings(
            db_session, {"task_routing_auto_threshold": 1.5}, admin_user
        )


@pytest.mark.asyncio
async def test_wrong_type_is_rejected(db_session, admin_user):
    with pytest.raises(SettingsValidationError):
        await settings_service.set_settings(db_session, {"clinic_open_hour": "eight"}, admin_user)


@pytest.mark.asyncio
async def test_read_only_setting_cannot_be_written(db_session, admin_user):
    with pytest.raises(SettingsValidationError):
        await settings_service.set_settings(db_session, {"sufficiency_floor": 0.2}, admin_user)


@pytest.mark.asyncio
async def test_close_hour_must_exceed_open_hour(db_session, admin_user):
    with pytest.raises(SettingsValidationError):
        await settings_service.set_settings(
            db_session, {"clinic_open_hour": 18, "clinic_close_hour": 9}, admin_user
        )


@pytest.mark.asyncio
async def test_floor_must_not_exceed_auto_threshold(db_session, admin_user):
    with pytest.raises(SettingsValidationError):
        await settings_service.set_settings(
            db_session,
            {"task_routing_auto_threshold": 0.60, "task_routing_floor": 0.95},
            admin_user,
        )


@pytest.mark.asyncio
async def test_a_rejected_batch_writes_nothing(db_session, admin_user):
    original = settings.clinic_open_hour
    with pytest.raises(SettingsValidationError):
        await settings_service.set_settings(
            db_session, {"clinic_open_hour": 7, "not_a_real_key": 1}, admin_user
        )
    assert settings.clinic_open_hour == original


@pytest.mark.asyncio
async def test_write_then_hydrate_applies_to_the_settings_singleton(db_session, admin_user):
    await settings_service.set_settings(
        db_session, {"task_routing_auto_threshold": 0.77}, admin_user
    )
    assert settings.task_routing_auto_threshold == 0.77

    # A fresh process would start from env defaults, then hydrate from the DB.
    settings.task_routing_auto_threshold = settings_service.ENV_DEFAULTS[
        "task_routing_auto_threshold"
    ]
    await settings_service.hydrate(db_session)
    assert settings.task_routing_auto_threshold == 0.77


@pytest.mark.asyncio
async def test_hydrate_with_empty_table_leaves_env_defaults(db_session):
    await settings_service.hydrate(db_session)
    assert settings.sufficiency_floor == settings_service.ENV_DEFAULTS["sufficiency_floor"]


@pytest.mark.asyncio
async def test_hydrate_ignores_rows_whose_key_left_the_registry(db_session):
    from app.models.app_setting import AppSetting

    db_session.add(AppSetting(key="retired_key", value={"v": 1}))
    await db_session.commit()
    await settings_service.hydrate(db_session)  # must not raise


@pytest.mark.asyncio
async def test_write_records_an_audit_event(db_session, admin_user):
    from sqlalchemy import select

    from app.models.audit import AuditEvent

    await settings_service.set_settings(db_session, {"clinic_open_hour": 7}, admin_user)
    events = (
        (await db_session.execute(select(AuditEvent).where(AuditEvent.action == "settings.update")))
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].details["key"] == "clinic_open_hour"
    assert events[0].details["new"] == 7
    assert events[0].actor_id == admin_user.id


@pytest.mark.asyncio
async def test_every_registry_key_exists_on_settings():
    for key in settings_service.SETTINGS_REGISTRY:
        assert hasattr(settings, key), f"{key} is in the registry but not on Settings"
