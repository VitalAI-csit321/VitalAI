from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.permissions import READ_AUDIT
from app.database import get_db
from app.models.case import IntakeCase
from app.models.user import User
from app.schemas.audit import AuditEventOut
from app.services import audit_service

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/by-case/{case_id}", response_model=list[AuditEventOut])
async def get_audit_for_case(
    case_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(READ_AUDIT)),
):
    events = await audit_service.get_events_for_case(db, case_id)

    # audit_events.case_id has a real FK to intake_cases, so a read against a
    # case_id that doesn't exist (a typo, a stale link, deliberate probing)
    # can't be attached to that column without violating the constraint. The
    # read attempt is still logged either way; the attempted id always lands
    # in details, which carries no FK.
    case_exists = await db.get(IntakeCase, case_id) is not None
    await audit_service.record_event(
        db,
        actor=actor,
        action="audit.read",
        case_id=case_id if case_exists else None,
        details={"case_id": str(case_id)},
    )
    await db.commit()

    return events
