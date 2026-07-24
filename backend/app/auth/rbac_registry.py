"""Introspects the FastAPI app's actual dependency graph to answer, for any
registered route, what RBAC check (if any) gates it. Single source of truth
for tests/test_rbac_enforcement.py — never re-derive this by hand.

FastAPI (this project's pinned 0.139.2) leaves routes registered via
app.include_router() as opaque _IncludedRouter wrappers in app.routes rather
than flattening them eagerly: the wrapper's own .original_router.routes
holds the real APIRoute objects, and .include_context.prefix holds the
prefix passed to include_router(), which is NOT merged into route.path.
Both were confirmed empirically against this app before writing this walk,
not assumed from FastAPI's general docs — re-verify against a throwaway
app.routes dump if this project ever upgrades FastAPI/Starlette, since this
relies on a private (underscore-prefixed) class name that isn't a stable
public API.
"""

from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.routing import APIRoute, _IncludedRouter
from starlette.routing import BaseRoute

RbacCheck = tuple[str, frozenset]


@dataclass(frozen=True)
class RouteRbacEntry:
    method: str
    path: str
    rbac_check: RbacCheck | None


def _iter_api_routes(routes: list[BaseRoute], prefix: str = "") -> Iterator[tuple[str, APIRoute]]:
    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
        elif isinstance(route, _IncludedRouter):
            yield from _iter_api_routes(
                route.original_router.routes, prefix + route.include_context.prefix
            )
        # Any other route type (FastAPI's own /openapi.json, /docs, /redoc are
        # plain starlette.routing.Route, not APIRoute) is intentionally skipped —
        # they're not application routes and need no RBAC gate.


def get_rbac_registry(app: FastAPI) -> list[RouteRbacEntry]:
    """One entry per (method, full path) for every route this app actually
    serves, with the RBAC check (if any) FastAPI will run before the handler.
    """
    entries: list[RouteRbacEntry] = []
    for full_path, route in _iter_api_routes(list(app.routes)):
        rbac_check: RbacCheck | None = None
        for dependency in route.dependant.dependencies:
            check = getattr(dependency.call, "rbac_check", None)
            if check is not None:
                rbac_check = check
                break
        for method in route.methods or ():
            entries.append(RouteRbacEntry(method=method, path=full_path, rbac_check=rbac_check))
    return entries
