import pytest

from app import observability


def setup_function():
    observability.reset()


def test_snapshot_is_empty_before_any_request():
    snap = observability.latency_snapshot()
    assert snap == {"count": 0, "avg_ms": None, "p95_ms": None}


def test_average_and_p95_over_recorded_samples():
    for ms in [10.0, 20.0, 30.0, 40.0]:
        observability.record_latency(ms)
    snap = observability.latency_snapshot()
    assert snap["count"] == 4
    assert snap["avg_ms"] == 25.0
    assert snap["p95_ms"] == 40.0


def test_window_is_bounded_so_memory_cannot_grow():
    for i in range(1200):
        observability.record_latency(float(i))
    assert observability.latency_snapshot()["count"] == 500


def test_uptime_is_none_until_marked_then_counts_up():
    assert observability.uptime_seconds() is None
    observability.mark_started()
    assert observability.uptime_seconds() >= 0.0


@pytest.mark.asyncio
async def test_middleware_records_a_sample(client):
    observability.reset()
    await client.get("/health")
    assert observability.latency_snapshot()["count"] >= 1
