from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.permissions import READ_AUDIT
from app.database import get_db
from app.models.case import IntakeCase
from app.models.user import User
from app.schemas.audit import AuditEventListResponse, AuditEventOut
from app.services import audit_service

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=AuditEventListResponse)
async def list_audit_events(
    actor_id: UUID | None = None,
    action: str | None = None,
    risk_level: str | None = Query(None, pattern="^(High|Medium|Low)$"),
    outcome: str | None = None,
    case_id: UUID | None = None,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(READ_AUDIT)),
):
    items, total = await audit_service.list_events(
        db,
        actor_id=actor_id,
        action=action,
        risk_level=risk_level,
        outcome=outcome,
        case_id=case_id,
        from_time=from_time,
        to_time=to_time,
        limit=limit,
        offset=offset,
    )

    await audit_service.record_event(
        db,
        actor=actor,
        action="audit.list_read",
        details={
            "filters": {
                "actor_id": str(actor_id) if actor_id else None,
                "action": action,
                "risk_level": risk_level,
                "outcome": outcome,
                "case_id": str(case_id) if case_id else None,
            }
        },
    )
    await db.commit()

    return AuditEventListResponse(
        items=[AuditEventOut.model_validate(e) for e in items], total=total
    )


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
