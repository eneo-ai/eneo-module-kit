import time
import unittest

import httpx2
from fastapi import APIRouter, Depends, FastAPI, Request, WebSocket
from fastapi.routing import APIRoute, APIWebSocketRoute
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from eneo_module_bff.auth import SESSION_COOKIE, ModuleAuth, ModuleSession, ModuleUser
from eneo_module_bff.deps import require_same_origin, require_session, upstream_auth_headers
from eneo_module_bff.settings import Settings

MODULE_ORIGIN = "https://module.example.test"


def build_app(module_public_url: str = MODULE_ORIGIN) -> tuple[FastAPI, ModuleAuth]:
    """An app whose routes hold no ModuleAuth: the dependencies find it on app.state."""
    settings = Settings(
        eneo_backend_url="https://eneo.example.test",
        eneo_public_url="https://eneo.example.test",
        module_public_url=module_public_url,
        module_key="test-module",
        eneo_api_key="test-key",
        session_secret="x" * 48,
        cookie_secure=False,
    )
    auth = ModuleAuth(settings=settings, http_client=httpx2.AsyncClient())
    app = FastAPI()
    app.state.module_auth = auth

    @app.get("/read", dependencies=[Depends(require_session)])
    async def read() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/write", dependencies=[Depends(require_session), Depends(require_same_origin)])
    async def write() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/upstream", dependencies=[Depends(require_session)])
    async def upstream(request: Request) -> dict[str, str]:
        return upstream_auth_headers(request)

    @app.websocket("/socket")
    async def socket(websocket: WebSocket, _: ModuleSession = Depends(require_session)) -> None:
        await websocket.accept()
        await websocket.close()

    return app, auth


WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def dependency_calls(dependant) -> set:
    """Every dependency of a route, however deep: its own, its parameters', and what those depend on."""
    calls = set()
    for sub in dependant.dependencies:
        calls.add(sub.call)
        calls |= dependency_calls(sub)
    return calls


def unguarded_routes(*routers: APIRouter) -> list[str]:
    """What a module author may have forgotten on the routes of ``routers``.

    Every route needs ``require_session``. A route that writes, and every WebSocket route (a handshake acts for the
    user too, and ``APIWebSocketRoute`` has no ``.methods``), also needs ``require_same_origin``. A route this
    cannot check (a mount, a raw route, a nested include) is reported, never passed over.

    It walks the module's routers, not ``app.routes``: FastAPI keeps an included router as one object there.
    The template's test (Phase 3) reuses it.
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


async def module_dependency(_: ModuleSession = Depends(require_session)) -> None:
    """A module's own dependency that rests on require_session."""


class RouteWalkerTests(unittest.TestCase):
    def test_a_router_with_every_guard_has_nothing_unguarded(self) -> None:
        router = APIRouter()

        @router.get("/api/by-route-dependency", dependencies=[Depends(require_session)])
        async def by_route_dependency() -> None: ...

        @router.get("/api/by-parameter")
        async def by_parameter(_: ModuleSession = Depends(require_session)) -> None: ...

        @router.get("/api/by-its-own-dependency", dependencies=[Depends(module_dependency)])
        async def by_its_own_dependency() -> None: ...

        @router.post("/api/write", dependencies=[Depends(require_session), Depends(require_same_origin)])
        async def write() -> None: ...

        @router.websocket("/api/socket", dependencies=[Depends(require_same_origin)])
        async def socket(websocket: WebSocket, _: ModuleSession = Depends(require_session)) -> None: ...

        self.assertEqual(unguarded_routes(router), [])

    def test_a_forgotten_guard_is_reported_on_every_kind_of_route(self) -> None:
        router = APIRouter()

        @router.get("/api/open")
        async def open_route() -> None: ...

        @router.delete("/api/write-without-origin", dependencies=[Depends(require_session)])
        async def write_without_origin() -> None: ...

        @router.websocket("/api/socket-without-origin")
        async def socket_without_origin(websocket: WebSocket, _: ModuleSession = Depends(require_session)) -> None: ...

        @router.websocket("/socket-without-session", dependencies=[Depends(require_same_origin)])
        async def socket_without_session(websocket: WebSocket) -> None: ...

        self.assertEqual(
            unguarded_routes(router),
            [
                "GET /api/open: no require_session",
                "DELETE /api/write-without-origin: no require_same_origin",
                "WebSocket /api/socket-without-origin: no require_same_origin",
                "WebSocket /socket-without-session: no require_session",
            ],
        )

    def test_a_route_it_cannot_check_is_reported(self) -> None:
        router = APIRouter()
        router.mount("/files", FastAPI())

        self.assertEqual(unguarded_routes(router), ["/files: a Mount cannot be checked"])

    def test_the_guards_the_walker_looks_for_are_the_ones_that_act(self) -> None:
        router = APIRouter()

        @router.websocket("/api/socket", dependencies=[Depends(require_same_origin)])
        async def socket(websocket: WebSocket, _: ModuleSession = Depends(require_session)) -> None:
            await websocket.accept()
            await websocket.close()

        app, auth = build_app()
        app.include_router(router)
        client = TestClient(app)
        self.assertEqual(unguarded_routes(router), [])
        with self.assertRaises(WebSocketDisconnect):  # the guards are really on the route
            with client.websocket_connect("/api/socket"):
                pass


class DependencyTests(unittest.TestCase):
    def setUp(self) -> None:
        app, self.auth = build_app()
        self.client = TestClient(app)

    def build(self, module_public_url: str) -> None:
        app, self.auth = build_app(module_public_url)
        self.client = TestClient(app)

    def sign_in(self) -> None:
        now = int(time.time())
        session_id = self.auth.sessions.create(
            ModuleSession(
                access_token="module-user-token",
                expires_at=now + 900,
                refresh_at=now + 450,
                session_expires_at=now + 3600,
                module_key="test-module",
                tenant_id="tenant-id",
                user=ModuleUser(id="user-id", email="user@example.test"),
            )
        )
        self.client.cookies.set(SESSION_COOKIE, session_id)

    def test_a_request_without_a_session_is_401_and_says_which_credential_is_missing(self) -> None:
        response = self.client.get("/read")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["x-auth-required"], "session")

    def test_a_write_from_another_origin_is_403(self) -> None:
        self.sign_in()

        for origin in ("https://attacker.example.test", None):
            with self.subTest(origin=origin):
                headers = {"Origin": origin} if origin else {}
                self.assertEqual(self.client.post("/write", headers=headers).status_code, 403)

    def test_the_origin_is_compared_in_canonical_form(self) -> None:
        # The configured URL may be written any way; a browser sends scheme and host in lower case and no default port.
        for configured in ("https://Module.Example.TEST", "https://module.example.test:443", "HTTPS://MODULE.example.test:443/"):
            self.build(configured)
            self.sign_in()
            with self.subTest(configured=configured):
                self.assertEqual(self.client.post("/write", headers={"Origin": MODULE_ORIGIN}).status_code, 200)
                self.assertEqual(self.client.post("/write", headers={"Origin": "https://MODULE.example.test"}).status_code, 200)
                for other in (
                    "https://module.example.test:8443",
                    "http://module.example.test",
                    "https://module.example.test/evil",
                    "https://evil.example.test",
                    "https://module.example.test.evil.example",
                    "null",
                ):
                    self.assertEqual(self.client.post("/write", headers={"Origin": other}).status_code, 403, other)

    def test_a_session_and_the_modules_origin_is_let_through(self) -> None:
        self.sign_in()

        self.assertEqual(self.client.get("/read").status_code, 200)
        self.assertEqual(self.client.post("/write", headers={"Origin": MODULE_ORIGIN}).status_code, 200)

    def test_upstream_auth_headers_carry_the_service_key_and_the_users_token(self) -> None:
        self.sign_in()

        self.assertEqual(
            self.client.get("/upstream").json(),
            {"X-API-Key": "test-key", "Authorization": "Bearer module-user-token"},
        )

    def test_a_websocket_without_a_session_is_refused_before_it_is_accepted(self) -> None:
        with self.assertRaises(WebSocketDisconnect) as refused:
            with self.client.websocket_connect("/socket"):
                pass

        self.assertEqual(refused.exception.code, 1008)

    def test_a_websocket_with_a_session_is_accepted(self) -> None:
        self.sign_in()

        with self.client.websocket_connect("/socket"):
            pass


if __name__ == "__main__":
    unittest.main()
