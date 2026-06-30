from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.triage import TriageRequest, TriageResponse
from app.services import triage_service
from app.services.triage_service import ConsentGatingError

router = APIRouter(prefix="/triage", tags=["triage"])


@router.post("", response_model=TriageResponse)
async def triage_endpoint(
    request: TriageRequest,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    try:
        return await triage_service.classify(db, request, actor)
    except ConsentGatingError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
