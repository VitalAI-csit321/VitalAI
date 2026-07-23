from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_roles
from app.database import get_db
from app.models.human_review import TaskStatus, TaskType
from app.models.user import User, UserRole
from app.schemas.pagination import Page, PageParams
from app.schemas.review import ReviewTaskCreate, ReviewTaskOut, ReviewTaskUpdate
from app.services import review_service
from app.services.review_service import ReviewStateError

router = APIRouter(prefix="/review-tasks", tags=["review"])


@router.post("", response_model=ReviewTaskOut, status_code=status.HTTP_201_CREATED)
async def create_review_task_endpoint(
    payload: ReviewTaskCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    return await review_service.create_task(db, payload, actor)


@router.get("", response_model=Page[ReviewTaskOut])
async def list_review_tasks_endpoint(
    page: PageParams = Depends(),
    status: list[TaskStatus] | None = Query(default=None),
    task_type: list[TaskType] | None = Query(default=None),
    assigned_to: UUID | None = Query(default=None),
    case_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    items, total = await review_service.list_tasks(
        db,
        limit=page.limit,
        offset=page.offset,
        status=status,
        task_type=task_type,
        assigned_to=assigned_to,
        case_id=case_id,
    )
    return Page[ReviewTaskOut](
        items=[ReviewTaskOut.model_validate(task) for task in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


# NOTE: must stay above /{task_id} — see the same note in routes/intake.py.
@router.get("/summary")
async def review_summary_endpoint(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict[str, dict[str, int]]:
    """Open task counts per type — the queue page's tab badges."""
    return {"open_counts": await review_service.queue_counts(db)}


@router.get("/{task_id}", response_model=ReviewTaskOut)
async def get_review_task_endpoint(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    task = await review_service.get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review task not found")
    return task


@router.patch("/{task_id}", response_model=ReviewTaskOut)
async def update_review_task_endpoint(
    task_id: UUID,
    payload: ReviewTaskUpdate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_roles(UserRole.OPS_MANAGER, UserRole.ADMIN)),
):
    try:
        task = await review_service.update_task(db, task_id, payload, actor)
    except ReviewStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review task not found")
    return task
