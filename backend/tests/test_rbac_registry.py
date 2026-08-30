from app.auth.permissions import MANAGE_APPOINTMENTS_ALL, MANAGE_CASES, MANAGE_OWN_CALENDAR
from app.auth.rbac_registry import get_rbac_registry
from app.main import app
from app.models.user import UserRole


def _find(registry, method, path):
    return next(e for e in registry if e.method == method and e.path == path)


def test_finds_known_permission_gated_route():
    entry = _find(get_rbac_registry(app), "POST", "/api/v1/triage")
    assert entry.rbac_check == ("permission", frozenset({MANAGE_CASES}))


def test_finds_known_any_permission_gated_route():
    entry = _find(get_rbac_registry(app), "GET", "/api/v1/appointments")
    assert entry.rbac_check == (
        "any_permission",
        frozenset({MANAGE_APPOINTMENTS_ALL, MANAGE_OWN_CALENDAR}),
    )


def test_finds_known_role_gated_route():
    entry = _find(get_rbac_registry(app), "GET", "/api/v1/llm/status")
    assert entry.rbac_check == ("roles", frozenset({UserRole.ADMIN, UserRole.OPERATOR}))


def test_reports_none_for_route_with_no_rbac_gate():
    entry = _find(get_rbac_registry(app), "GET", "/health")
    assert entry.rbac_check is None


def test_excludes_fastapi_internal_routes():
    paths = {e.path for e in get_rbac_registry(app)}
    assert "/openapi.json" not in paths
    assert "/docs" not in paths
    assert "/redoc" not in paths


def test_resolves_full_prefixed_paths():
    paths = {e.path for e in get_rbac_registry(app)}
    assert "/api/v1/triage" in paths
    assert "/health" in paths  # included without the /api/v1 prefix, confirms prefix
    # resolution is per-router (via _IncludedRouter.include_context.prefix), not hardcoded.


def test_total_route_count():
    registry = get_rbac_registry(app)
    # 72 real application routes as of this writing (71 after reconciling two
    # branches that each independently ported origin/feature/task-call-models,
    # so their two prior counts, 63 and 60, both already included the shared
    # base /calls and /tasks routes and can't just be summed; +1 for
    # POST /api/v1/calls/transcribe, the call-transcription connector).
    # Counted directly off the merged app's own route table, not derived from
    # either branch's stale number. Bump deliberately when a route is added or
    # removed; an unexpected change here means the walker itself regressed
    # (e.g. double-counting via bad recursion), not that this number merely
    # went stale.
    # 74 as of the inbox delete/read feature: +2 for DELETE /api/v1/tasks/{task_id}
    # and POST /api/v1/tasks/{task_id}/read.
    # 82 as of the appointments calendar feature (Plan 2): +8 for GET /doctors,
    # GET /appointments/calendar, GET /appointments/calendar/markers,
    # GET /appointments/day, GET /appointments/availability,
    # GET /appointments/{appointment_id}, PATCH /appointments/{appointment_id},
    # and POST /appointments/{appointment_id}/complete.
    # 83 as of the appointments data-paths feature (Plan 3): +1 for
    # POST /appointments/suggest.
    # 84 as of the dashboard workflow-status fix: +1 for GET /human-review/stats/daily.
    assert len({(e.method, e.path) for e in registry}) == 84
