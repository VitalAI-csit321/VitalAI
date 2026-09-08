"""In-process request metrics for the Platform Ops dashboard.

Deliberately not a metrics library. This feeds two tiles on one page, so a
bounded deque is the whole implementation.

# ponytail: per-process, in-memory, lost on restart. If we ever need real
# historical metrics or more than one worker, this is the seam to replace with
# Prometheus rather than something to grow.
"""

import time
from collections import deque

_WINDOW = 500
_latencies: deque[float] = deque(maxlen=_WINDOW)
_started_at: float | None = None


def mark_started() -> None:
    global _started_at
    _started_at = time.monotonic()


def uptime_seconds() -> float | None:
    return None if _started_at is None else time.monotonic() - _started_at


def record_latency(ms: float) -> None:
    _latencies.append(ms)


def latency_snapshot() -> dict:
    if not _latencies:
        return {"count": 0, "avg_ms": None, "p95_ms": None}
    ordered = sorted(_latencies)
    # Nearest-rank p95; on a 500-sample window the interpolation nicety of a
    # real percentile implementation buys nothing here.
    index = min(len(ordered) - 1, int(len(ordered) * 0.95))
    return {
        "count": len(_latencies),
        "avg_ms": round(sum(_latencies) / len(_latencies), 1),
        "p95_ms": round(ordered[index], 1),
    }


def reset() -> None:
    """Test helper. Never call from application code."""
    global _started_at
    _latencies.clear()
    _started_at = None
