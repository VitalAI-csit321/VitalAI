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
    # 63 real application routes as of this writing (54 prior count + 9
    # routes ported from origin/feature/task-call-models: POST/GET /calls,
    # GET /calls/{id}, POST /calls/{id}/route, POST /calls/{id}/override-
    # routing, POST /calls/{id}/escalate, POST/GET /tasks, GET /tasks/{id} -
    # the Escalations page's real backend), confirmed via a direct
    # app.routes walk before this test is written. Bump deliberately when a
    # route is added or removed; an unexpected change here means the walker
    # itself regressed (e.g. double-counting via bad recursion), not that
    # this number merely went stale.
    assert len({(e.method, e.path) for e in registry}) == 63
