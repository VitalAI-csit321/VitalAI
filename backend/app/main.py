import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.config import settings
from app.limiter import limiter
from app.routes import (
    appointments,
    assignments,
    audit,
    auth,
    clinical_documents,
    consent,
    health,
    intake,
    llm,
    patients,
    rag,
    review_tasks,
    routing,
    tasks,
    triage,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    is_prod = settings.app_env == "production"
    if is_prod and settings.synthetic_only:
        raise RuntimeError(
            "SYNTHETIC_ONLY=true is not allowed in production. "
            "Set SYNTHETIC_ONLY=false or change APP_ENV."
        )
    if is_prod and not settings.synthetic_only:
        logger.warning("Running in production mode with real patient data (SYNTHETIC_ONLY=false)")
    redacted = {
        "APP_ENV": settings.app_env,
        "LLM_PROVIDER": settings.llm_provider,
        "EMBEDDING_PROVIDER": settings.embedding_provider,
        "SYNTHETIC_ONLY": settings.synthetic_only,
        "DATABASE_URL": "***",
        "JWT_SECRET_KEY": "***",
        "MINIO_SECRET_KEY": "***",
    }
    logger.info("startup config: %s", redacted)
    yield


async def _rate_limit_handler(request: Request, exc: Exception) -> Response:
    """Type-correct wrapper so Starlette's add_exception_handler is satisfied."""
    assert isinstance(exc, RateLimitExceeded)
    return _rate_limit_exceeded_handler(request, exc)


app = FastAPI(
    title=f"{settings.app_name} — Phase One API",
    description="Backend for administrative intake, consent, triage, and routing.",
    version=settings.app_version,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next: RequestResponseEndpoint) -> Response:
    request_id = str(uuid4())
    request.state.request_id = request_id
    logger.info("request_id=%s method=%s path=%s", request_id, request.method, request.url.path)
    response: Response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# Public
app.include_router(health.router)

# Authenticated
API_PREFIX = "/api/v1"
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(intake.router, prefix=API_PREFIX)
app.include_router(consent.router, prefix=API_PREFIX)
app.include_router(triage.router, prefix=API_PREFIX)
app.include_router(routing.router, prefix=API_PREFIX)
app.include_router(llm.router, prefix=API_PREFIX)
app.include_router(audit.router, prefix=API_PREFIX)
app.include_router(patients.router, prefix=API_PREFIX)
app.include_router(assignments.router, prefix=API_PREFIX)
app.include_router(rag.router, prefix=API_PREFIX)
app.include_router(appointments.router, prefix=API_PREFIX)
app.include_router(clinical_documents.router, prefix=API_PREFIX)
app.include_router(review_tasks.router, prefix=API_PREFIX)
app.include_router(tasks.router, prefix=API_PREFIX)


@app.get("/")
def root() -> dict:
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/health",
    }
