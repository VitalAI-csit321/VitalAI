from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.permissions import VIEW_QUEUE
from app.database import get_db
from app.models.user import User
from app.schemas.email import EmailIngestRequest, EmailIngestResult, EmailOut
from app.services import email_service

router = APIRouter(prefix="/email", tags=["email"])


@router.post("/ingest", response_model=EmailIngestResult, status_code=status.HTTP_201_CREATED)
async def ingest_email_endpoint(
    payload: EmailIngestRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(VIEW_QUEUE)),
):
    try:
        email, task, gate, confidence = await email_service.ingest_email(db, payload, actor)
    except email_service.CaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    # ingest_email() always sets these before returning.
    assert task.category is not None
    assert task.target_role is not None
    # Drafting is a 90s-timeout model call, so it runs after the response
    # rather than holding it open. It gets ids, not rows: get_db's session is
    # closed by the time a background task runs.
    background_tasks.add_task(
        email_service.draft_reply_detached, task.id, email.id, actor.id, gate, confidence
    )
    return EmailIngestResult(
        email=EmailOut.model_validate(email),
        task_id=task.id,
        category=task.category,
        confidence=confidence,
        target_role=task.target_role,
        priority=task.priority,
        outcome=gate.outcome,
        override_reason=gate.override_reason,
    )
