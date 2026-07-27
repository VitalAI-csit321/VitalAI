import csv
import io
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.permissions import READ_AUDIT
from app.database import get_db
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
    format: str | None = Query(None, pattern="^csv$"),
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

    if format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "id",
                "timestamp",
                "actor_label",
                "actor_role",
                "action",
                "case_id",
                "risk_score",
                "risk_level",
                "outcome",
            ]
        )
        for event in items:
            writer.writerow(
                [
                    str(event.id),
                    event.timestamp.isoformat(),
                    event.actor_label or "",
                    event.actor_role or "",
                    event.action,
                    str(event.case_id) if event.case_id else "",
                    event.risk_score if event.risk_score is not None else "",
                    audit_service.risk_level_from_score(event.risk_score),
                    event.outcome or "",
                ]
            )
        buffer.seek(0)
        return StreamingResponse(
            iter([buffer.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=audit_events.csv"},
        )

    return AuditEventListResponse(
        items=[AuditEventOut.model_validate(e) for e in items], total=total
    )


@router.get("/verify")
async def verify_audit_chain_route(
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(READ_AUDIT)),
) -> dict:
    return await audit_service.verify_chain(db)


@router.get("/by-case/{case_id}", response_model=list[AuditEventOut])
async def get_audit_for_case(
    case_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(READ_AUDIT)),
):
    return await audit_service.get_events_for_case(db, case_id)


@router.get("/{event_id}", response_model=AuditEventOut)
async def get_audit_event(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(READ_AUDIT)),
):
    event = await audit_service.get_event_by_id(db, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Audit event not found")

    return event
