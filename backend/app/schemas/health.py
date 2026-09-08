from pydantic import BaseModel


class ServiceStatusOut(BaseModel):
    name: str
    detail: str
    status: str  # operational | degraded | down | disabled
    latency_ms: float | None = None
    note: str | None = None


class LatencyOut(BaseModel):
    count: int
    avg_ms: float | None
    p95_ms: float | None


class DetailedHealthOut(BaseModel):
    services: list[ServiceStatusOut]
    uptime_seconds: float | None
    latency: LatencyOut
    active_sessions: int
