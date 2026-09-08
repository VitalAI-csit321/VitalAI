"""Real dependency probes for the Platform Ops console.

Every probe is individually guarded: one unreachable dependency degrades its
own row and never takes the page down, because a health dashboard that 500s
when something is unhealthy is worse than useless.

boto3 is synchronous, so its probe runs in a thread rather than blocking the
event loop, matching how app/storage/object_storage.py is used elsewhere.
"""

import asyncio
import time
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.audit import AuditEvent
from app.schemas.health import ServiceStatusOut

_TIMEOUT_SECONDS = 3.0
_SESSION_WINDOW_MINUTES = 30


async def _timed(coro) -> tuple[bool, float, str | None]:
    start = time.perf_counter()
    try:
        await asyncio.wait_for(coro, _TIMEOUT_SECONDS)
        return True, (time.perf_counter() - start) * 1000, None
    except Exception as exc:  # noqa: BLE001 - any failure is a failed probe
        return False, (time.perf_counter() - start) * 1000, str(exc)[:200]


async def _probe_database(db: AsyncSession) -> ServiceStatusOut:
    ok, ms, err = await _timed(db.execute(select(1)))
    return ServiceStatusOut(
        name="Database",
        detail="PostgreSQL",
        status="operational" if ok else "down",
        latency_ms=round(ms, 1),
        note=err,
    )


def _probe_object_storage_sync() -> None:
    """Synchronous MinIO reachability check, run in a thread by the caller.

    Builds its own client with short timeouts and no retries rather than reusing
    _get_client(), whose boto3 defaults (60s connect, 5 retries) would hang this
    probe for minutes when the endpoint is unreachable. Separate named function
    so tests can monkeypatch it.
    """
    import boto3
    from botocore.client import Config

    from app.config import settings

    boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint,
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        config=Config(
            s3={"addressing_style": "path"},
            connect_timeout=2,
            read_timeout=2,
            retries={"max_attempts": 0},
        ),
    ).list_buckets()


async def _probe_object_storage() -> ServiceStatusOut:
    ok, ms, err = await _timed(asyncio.to_thread(_probe_object_storage_sync))
    return ServiceStatusOut(
        name="Object storage",
        detail=settings.minio_bucket,
        status="operational" if ok else "down",
        latency_ms=round(ms, 1),
        note=err,
    )


async def _probe_llm() -> ServiceStatusOut:
    async def call() -> None:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as http:
            res = await http.get(f"{settings.ollama_base_url}/api/tags")
            res.raise_for_status()

    ok, ms, err = await _timed(call())
    note = err
    if not ok and "://ollama" in settings.ollama_base_url:
        note = (
            "OLLAMA_BASE_URL points at the docker-internal hostname 'ollama', which a "
            "backend running on the host cannot resolve. " + (err or "")
        )
    return ServiceStatusOut(
        name="LLM provider",
        detail=f"{settings.llm_provider}: {settings.llm_model}",
        status="operational" if ok else "down",
        latency_ms=round(ms, 1),
        note=note,
    )


def _probe_outlook() -> ServiceStatusOut:
    if not settings.outlook_enabled:
        return ServiceStatusOut(
            name="Outlook connector",
            detail="Not enabled",
            status="disabled",
            note="Enable in .env and provide a token cache via scripts/outlook_login.py",
        )
    return ServiceStatusOut(
        name="Outlook connector",
        detail=settings.outlook_mailbox_address or "mailbox not configured",
        status="operational",
        note=f"Polling every {settings.outlook_poll_interval_seconds}s",
    )


async def check_all(db: AsyncSession) -> list[ServiceStatusOut]:
    database, storage, llm = await asyncio.gather(
        _probe_database(db), _probe_object_storage(), _probe_llm()
    )
    return [database, storage, llm, _probe_outlook()]


async def active_session_count(db: AsyncSession) -> int:
    """Distinct audit session ids seen recently.

    JWTs are stateless so there is no session table; the audit trail's
    session_id is the only real signal we have for "who is currently active".
    """
    since = datetime.now(UTC) - timedelta(minutes=_SESSION_WINDOW_MINUTES)
    result = await db.execute(
        select(func.count(func.distinct(AuditEvent.session_id))).where(
            AuditEvent.timestamp >= since, AuditEvent.session_id.is_not(None)
        )
    )
    return int(result.scalar() or 0)
