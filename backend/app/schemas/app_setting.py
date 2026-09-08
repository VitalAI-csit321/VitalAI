from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class SettingOut(BaseModel):
    key: str
    value: Any
    default: Any
    type: str
    group: str
    label: str
    help: str
    minimum: float | None
    maximum: float | None
    editable: bool
    updated_by: UUID | None
    updated_at: datetime | None


class SettingListResponse(BaseModel):
    items: list[SettingOut]


class SettingsUpdate(BaseModel):
    values: dict[str, Any]
