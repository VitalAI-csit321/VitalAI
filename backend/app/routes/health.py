from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.permissions import READ_AUDIT
from app.config import settings
from app.database import get_db
from app.models.user import User
from app.observability import latency_snapshot, uptime_seconds
from app.schemas.health import DetailedHealthOut, LatencyOut
from app.services import health_service

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict:
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
        "synthetic_only": settings.synthetic_only,
    }


detailed_router = APIRouter(prefix="/health", tags=["health"])


@detailed_router.get("/detailed", response_model=DetailedHealthOut)
async def detailed_health(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(READ_AUDIT)),
) -> DetailedHealthOut:
    return DetailedHealthOut(
        services=await health_service.check_all(db),
        uptime_seconds=uptime_seconds(),
        latency=LatencyOut(**latency_snapshot()),
        active_sessions=await health_service.active_session_count(db),
    )
