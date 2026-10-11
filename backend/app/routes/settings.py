from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.permissions import CONFIGURE_GOVERNANCE
from app.database import get_db
from app.models.app_setting import AppSetting
from app.models.user import User
from app.schemas.app_setting import SettingListResponse, SettingOut, SettingsUpdate
from app.services import settings_service
from app.services.settings_service import SettingsValidationError

router = APIRouter(prefix="/settings", tags=["settings"])


async def _build_list(db: AsyncSession) -> SettingListResponse:
    rows = {r.key: r for r in (await db.execute(select(AppSetting))).scalars().all()}
    items = []
    for key in settings_service.SETTINGS_REGISTRY:
        row = rows.get(key)
        value, default, spec = settings_service.shown(key)
        items.append(
            SettingOut(
                key=key,
                value=value,
                default=default,
                type=spec.type.__name__,
                group=spec.group,
                label=spec.label,
                help=spec.help,
                minimum=spec.minimum,
                maximum=spec.maximum,
                editable=spec.editable,
                updated_by=row.updated_by if row else None,
                updated_at=row.updated_at if row else None,
            )
        )
    return SettingListResponse(items=items)


@router.get("", response_model=SettingListResponse)
async def list_settings_endpoint(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(CONFIGURE_GOVERNANCE)),
):
    return await _build_list(db)


@router.patch("", response_model=SettingListResponse)
async def update_settings_endpoint(
    payload: SettingsUpdate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(CONFIGURE_GOVERNANCE)),
):
    try:
        await settings_service.set_settings(db, payload.values, actor)
    except SettingsValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return await _build_list(db)
