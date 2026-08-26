from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_any_permission
from app.auth.permissions import MANAGE_APPOINTMENTS_ALL, MANAGE_OWN_CALENDAR
from app.database import get_db
from app.models.user import User
from app.schemas.doctor import DoctorOut
from app.services import doctor_service

router = APIRouter(prefix="/doctors", tags=["doctors"])


@router.get("", response_model=list[DoctorOut])
async def list_doctors_endpoint(
    search: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_permission(MANAGE_APPOINTMENTS_ALL, MANAGE_OWN_CALENDAR)),
):
    return await doctor_service.list_doctors(db, search)
