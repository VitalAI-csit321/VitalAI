"""Systematic RBAC enforcement: every route is either RBAC-gated or on an
explicit, reviewed allowlist (test_every_route_has_an_rbac_gate_or_is_explicitly_allowlisted),
and every route's gate behaves correctly for all 4 roles via real HTTP
(test_route_permission_enforcement, added in the next task).

Both derive expected behavior from live code (app.auth.rbac_registry,
app.auth.permissions.ROLE_PERMISSIONS) — there is no hand-maintained
route-to-permission mapping to keep in sync. See
docs/superpowers/specs/2026-07-24-sec-rbac-enforcement-tests-design.md.
"""

from app.auth.rbac_registry import get_rbac_registry
from app.main import app

# Routes intentionally not permission-gated — either fully public (no auth at
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
    }
)


def test_every_route_has_an_rbac_gate_or_is_explicitly_allowlisted():
    for entry in get_rbac_registry(app):
        key = (entry.method, entry.path)
        if key in _NO_PERMISSION_GATE:
            assert entry.rbac_check is None, (
                f"{entry.method} {entry.path} is on the no-permission-gate allowlist "
                f"but has an RBAC gate attached — remove it from the allowlist"
            )
        else:
            assert entry.rbac_check is not None, (
                f"{entry.method} {entry.path} has no RBAC gate and is not on the "
                f"no-permission-gate allowlist — add Depends(require_permission(...)) "
                f"or add it to the allowlist if this is intentional"
            )
