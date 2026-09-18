from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.permissions import VIEW_CLINICAL
from app.auth.scoping import allowed_scopes, can_read_clinical
from app.database import get_db
from app.llm.guardrail import InputBlockedError
from app.models.user import User
from app.rag.answer import AnswerResult, answer_question
from app.rag.retrieval import IndexedDocument, RetrievalContext, list_indexed_documents
from app.schemas.rag import RagQueryRequest

router = APIRouter(prefix="/rag", tags=["rag"])


def _context(actor: User, patient_id: UUID) -> RetrievalContext:
    return RetrievalContext(
        patient_id=patient_id,
        allowed_scopes=list(allowed_scopes(actor)),
        role=actor.role.value,
        actor=str(actor.id),
    )


@router.get("/documents", response_model=list[IndexedDocument])
async def list_indexed_documents_endpoint(
    patient_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(VIEW_CLINICAL)),
):
    if not await can_read_clinical(db, actor, patient_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not permitted to read clinical records for this patient",
        )
    return await list_indexed_documents(db, _context(actor, patient_id))


@router.post("/query", response_model=AnswerResult)
async def rag_query_endpoint(
    payload: RagQueryRequest,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(VIEW_CLINICAL)),
):
    if not await can_read_clinical(db, actor, payload.patient_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not permitted to read clinical records for this patient",
        )

    ctx = _context(actor, payload.patient_id)
    try:
        return await answer_question(db, payload.question, ctx, actor)
    except InputBlockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="This request could not be processed.",
        ) from exc
