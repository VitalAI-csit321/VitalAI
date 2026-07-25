import sqlalchemy as sa
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


from fastapi import HTTPException, Query, status as http_status
from sqlalchemy import select
from app.models.audit import AuditEvent
from app.schemas.pagination import Page, PageParams


@router.get("", response_model=Page[AuditEventOut])
async def list_audit_events(
    page: PageParams = Depends(),
    search: str | None = Query(default=None),
    action: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(READ_AUDIT)),
):
    """Global filterable audit log — backs the Audit logs page."""
    from sqlalchemy import func, or_
    filters = []
    if action:
        filters.append(AuditEvent.action == action)
    if search:
        term = f"%{search}%"
        filters.append(or_(
            AuditEvent.action.ilike(term),
            AuditEvent.actor_id.cast(sa.String).ilike(term),
        ))

    count_stmt = select(func.count()).select_from(AuditEvent)
    page_stmt = select(AuditEvent)
    for f in filters:
        count_stmt = count_stmt.where(f)
        page_stmt = page_stmt.where(f)

    total = (await db.execute(count_stmt)).scalar_one()
    result = await db.execute(
        page_stmt.order_by(AuditEvent.timestamp.desc()).limit(page.limit).offset(page.offset)
    )
    return Page[AuditEventOut](
        items=[AuditEventOut.model_validate(e) for e in result.scalars().all()],
        total=total, limit=page.limit, offset=page.offset,
    )


@router.get("/{event_id}", response_model=AuditEventOut)
async def get_audit_event(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(READ_AUDIT)),
):
    """Single audit event detail — backs the Audit event detail page."""
    event = await db.get(AuditEvent, event_id)
    if event is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Audit event not found")
    return event
