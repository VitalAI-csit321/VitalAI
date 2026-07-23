"""Record & Information Retrieval endpoint.

The FR-RAG-01/02/03 pipeline (app/rag/) was fully implemented but had no HTTP
route — nothing could reach it. This is that route.

PROVISIONAL — two decisions in docs/FR-RAG-01_handoff.md are still open and
this route is where they surface. Both are marked below. Neither is resolved
here; both fail closed in the meantime.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.user import User, UserRole
from app.rag.answer import answer_question
from app.rag.retrieval import RetrievalContext
from app.schemas.rag import CitationOut, RagAnswerOut, RagQueryRequest

router = APIRouter(prefix="/rag", tags=["rag"])


# PROVISIONAL — reconcile with Matthew (handoff item 6).
#
# The handoff is explicit that RetrievalContext.role is a *clinical-access*
# role and is deliberately NOT app.models.user.UserRole (staff app-login
# roles), and that whether the two should ever converge is undecided. This map
# converges them anyway, because a route has to resolve *something* server-side
# and the alternative — letting the client name its own allowed_scopes — is not
# an access boundary at all.
#
# It is deliberately the narrowest defensible reading, and fails closed: an
# unknown role gets no scopes and therefore retrieves nothing (the security
# filter's `access_scope IN ()` matches zero rows) rather than defaulting open.
# Nobody currently reaches "sensitive". Do not widen this without the
# ratification pass.
_ROLE_SCOPES: dict[UserRole, list[str]] = {
    UserRole.FRONT_DESK: ["general"],
    UserRole.OPS_MANAGER: ["general", "restricted"],
    UserRole.ADMIN: ["general", "restricted"],
}


@router.post("/query", response_model=RagAnswerOut)
async def rag_query_endpoint(
    payload: RagQueryRequest,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    """Answer a question from one patient's records, with citations.

    PROVISIONAL — reconcile with Matthew (handoff item 2): patient_id arrives
    from the client because no case→patient link exists in the schema yet.
    Until it does, this endpoint cannot verify that the caller has any business
    reading the patient they named. That is a real gap, not a stylistic one —
    it must close before this touches anything but synthetic data.
    """
    allowed_scopes = _ROLE_SCOPES.get(actor.role, [])
    if not allowed_scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{actor.role.value}' has no record-retrieval scopes assigned.",
        )

    ctx = RetrievalContext(
        patient_id=payload.patient_id,
        allowed_scopes=allowed_scopes,
        role=actor.role.value,
        actor=actor.email,
    )

    try:
        result = await answer_question(db, payload.question, ctx)
    except RuntimeError as exc:  # pgvector missing, embedding provider down
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except ValueError as exc:  # embedding dimension mismatch
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc

    gate = result.gate_outcome
    return RagAnswerOut(
        answer=result.answer,
        refusal_source=result.refusal_source,
        decision=gate.decision,
        sufficient=gate.sufficient,
        reason=gate.reason,
        confidence=gate.confidence,
        confidence_source=gate.confidence_source,
        top_score=gate.top_score,
        citations=[
            CitationOut(
                chunk_id=chunk.chunk_id,
                source_document_id=chunk.source_document_id,
                doc_type=chunk.doc_type,
                chunk_index=chunk.chunk_index,
                attachment_uri=chunk.attachment_uri,
                score=chunk.score,
                content=chunk.content,
            )
            for chunk in gate.chunks
        ],
    )
