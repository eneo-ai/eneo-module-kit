"""The route walker of packages/bff/tests/test_deps.py, copied (it is tested there): what a module author may have
forgotten on the routes of a router."""

from fastapi import APIRouter
from fastapi.routing import APIRoute, APIWebSocketRoute

from eneo_module_bff import require_same_origin, require_session

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def dependency_calls(dependant) -> set:
    """Every dependency of a route, however deep: its own, its parameters', and what those depend on."""
    calls = set()
    for sub in dependant.dependencies:
        calls.add(sub.call)
        calls |= dependency_calls(sub)
    return calls


def unguarded_routes(*routers: APIRouter) -> list[str]:
    """Every route needs ``require_session``. A route that writes, and every WebSocket route (a handshake acts for the
    user too, and ``APIWebSocketRoute`` has no ``.methods``), also needs ``require_same_origin``. A route this cannot
    check (a mount, a raw route, a nested include) is reported, never passed over.

    It walks the module's routers, not ``app.routes``: FastAPI keeps an included router as one object there.
    """
    problems = []
    for router in routers:
        for route in router.routes:
            if isinstance(route, APIWebSocketRoute):
                label, writes = f"WebSocket {route.path}", True
            elif isinstance(route, APIRoute):
                label, writes = f"{', '.join(sorted(route.methods - {'HEAD'}))} {route.path}", bool(route.methods & WRITE_METHODS)
            else:
                problems.append(f"{getattr(route, 'path', '?')}: a {type(route).__name__} cannot be checked")
                continue
            calls = dependency_calls(route.dependant)
            if require_session not in calls:
                problems.append(f"{label}: no require_session")
            if writes and require_same_origin not in calls:
                problems.append(f"{label}: no require_same_origin")
    return problems
