from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.audit import AuditEventOut
from app.services import audit_service

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/by-case/{case_id}", response_model=list[AuditEventOut])
async def get_audit_for_case(
    case_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
):
    return await audit_service.get_events_for_case(db, case_id)
