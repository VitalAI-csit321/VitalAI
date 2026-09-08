"""Systematic RBAC enforcement: every route is either RBAC-gated or on an
explicit, reviewed allowlist (test_every_route_has_an_rbac_gate_or_is_explicitly_allowlisted),
and every route's gate behaves correctly for all 4 roles via real HTTP
(test_route_permission_enforcement, added in the next task).

Both derive expected behavior from live code (app.auth.rbac_registry,
app.auth.permissions.ROLE_PERMISSIONS); there is no hand-maintained
route-to-permission mapping to keep in sync. See
docs/superpowers/specs/2026-07-24-sec-rbac-enforcement-tests-design.md.
"""

import re
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.auth.permissions import ROLE_PERMISSIONS
from app.auth.rbac_registry import RouteRbacEntry, get_rbac_registry
from app.main import app
from app.models.user import UserRole

# Routes intentionally not permission-gated: either fully public (no auth at
# all) or authenticated-but-no-specific-permission-required (any logged-in
# user, e.g. reading your own profile). This is the one hand-maintained list
# in this file, kept deliberately small and meant to be reviewed on every
# change, not grown casually.
_NO_PERMISSION_GATE: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/health"),
        ("GET", "/"),
        ("POST", "/api/v1/auth/register"),
        ("POST", "/api/v1/auth/login"),
        ("GET", "/api/v1/auth/me"),
        ("POST", "/api/v1/auth/me/password"),
    }
)


def test_every_route_has_an_rbac_gate_or_is_explicitly_allowlisted():
    for entry in get_rbac_registry(app):
        key = (entry.method, entry.path)
        if key in _NO_PERMISSION_GATE:
            assert entry.rbac_check is None, (
                f"{entry.method} {entry.path} is on the no-permission-gate allowlist "
                f"but has an RBAC gate attached, remove it from the allowlist"
            )
        else:
            assert entry.rbac_check is not None, (
                f"{entry.method} {entry.path} has no RBAC gate and is not on the "
                f"no-permission-gate allowlist, add Depends(require_permission(...)) "
                f"or add it to the allowlist if this is intentional"
            )


_PLACEHOLDER_PATH_PARAM = "00000000-0000-0000-0000-000000000000"
_PATH_PARAM_PATTERN = re.compile(r"\{[^}]+\}")

# Built once at collection time so pytest can report each (route, role) pair
# as its own named test case rather than one loop with a buried assertion.
_GATED_ROUTES = [e for e in get_rbac_registry(app) if e.rbac_check is not None]


def _resolve_path(path: str) -> str:
    return _PATH_PARAM_PATTERN.sub(_PLACEHOLDER_PATH_PARAM, path)


def _role_satisfies(role: UserRole, rbac_check: tuple[str, frozenset]) -> bool:
    kind, values = rbac_check
    if kind == "roles":
        return role in values
    held = ROLE_PERMISSIONS[role]
    if kind == "permission":
        return values <= held
    if kind == "any_permission":
        return bool(values & held)
    raise ValueError(f"unknown rbac_check kind: {kind}")


@pytest.mark.parametrize(
    "entry", _GATED_ROUTES, ids=[f"{e.method}:{e.path}" for e in _GATED_ROUTES]
)
@pytest.mark.parametrize("test_role", list(UserRole))
async def test_route_permission_enforcement(
    client: AsyncClient,
    test_role: UserRole,
    entry: RouteRbacEntry,
    role_headers: dict[UserRole, dict],
):
    assert entry.rbac_check is not None
    headers = role_headers[test_role]
    path = _resolve_path(entry.path)
    method = entry.method.lower()
    request_kwargs: dict = {"headers": headers}
    if entry.method in {"POST", "PUT", "PATCH"}:
        request_kwargs["json"] = {}

    # POST /api/v1/llm/ping makes a real, unmocked network call to the
    # configured LLM provider; this test hits every gated route generically
    # with a blank request, including this one. Only this assertion cares
    # whether the permission gate let the request through, not whether an
    # LLM is actually reachable, so mock get_llm() here rather than depend on
    # a live provider (matches how tests/test_llm.py isolates its own
    # provider tests from a live network dependency).
    fake_llm = AsyncMock()
    fake_llm.ainvoke.return_value = "pong"
    with patch("app.routes.llm.get_llm", return_value=fake_llm):
        response = await getattr(client, method)(path, **request_kwargs)

    expected_denied = not _role_satisfies(test_role, entry.rbac_check)
    if expected_denied:
        assert response.status_code == 403, (
            f"{test_role.value} expected 403 on {entry.method} {entry.path}, "
            f"got {response.status_code}"
        )
    else:
        assert response.status_code != 403 and response.status_code != 500, (
            f"{test_role.value} expected non-403/non-500 on {entry.method} {entry.path}, "
            f"got {response.status_code}"
        )
