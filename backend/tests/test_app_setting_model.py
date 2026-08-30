import pytest
from sqlalchemy import select

from app.models.app_setting import AppSetting


@pytest.mark.asyncio
async def test_app_setting_roundtrips_each_value_shape(db_session):
    rows = [
        AppSetting(key="a_bool", value={"v": True}),
        AppSetting(key="a_float", value={"v": 0.85}),
        AppSetting(key="a_list", value={"v": ["x", "y"]}),
        AppSetting(key="a_dict", value={"v": {"k": "role"}}),
    ]
    db_session.add_all(rows)
    await db_session.commit()

    found = (await db_session.execute(select(AppSetting).order_by(AppSetting.key))).scalars().all()
    by_key = {r.key: r.value["v"] for r in found}
    assert by_key == {
        "a_bool": True,
        "a_float": 0.85,
        "a_list": ["x", "y"],
        "a_dict": {"k": "role"},
    }
    assert found[0].updated_at is not None
