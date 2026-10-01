import asyncio
import os
import unittest
from unittest.mock import patch

import httpx
from fastapi import APIRouter
from fastapi.testclient import TestClient

from eneo_module_bff.app import create_app
from eneo_module_bff.auth import ModuleAuth
from eneo_module_bff.settings import Settings


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "eneo_backend_url": "https://eneo.example.test",
        "eneo_public_url": "https://eneo.example.test",
        "module_public_url": "https://module.example.test",
        "module_key": "test-module",
        "eneo_api_key": "test-key",
        "session_secret": "x" * 48,
        "cookie_secure": False,
    }
    return Settings(**(values | overrides))


def module_router() -> APIRouter:
    """What a module declares before an app exists: one route under /api, one under /api/eneo."""
    router = APIRouter()

    @router.get("/api/mine")
    async def mine() -> dict[str, str]:
        return {"own": "mine"}

    @router.post("/api/eneo/things/{thing_id}/files")
    async def upload(thing_id: str) -> dict[str, str]:
        return {"own": thing_id}

    return router


class AppFactoryTests(unittest.TestCase):
    def injected_client(self) -> httpx.AsyncClient:
        client = httpx.AsyncClient()
        self.addCleanup(lambda: asyncio.run(client.aclose()))
        return client

    def test_health_answers_on_both_paths(self) -> None:
        client = TestClient(create_app(make_settings(), http_client=self.injected_client()))

        for path in ("/health", "/api/healthz"):
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual((response.status_code, response.json()), (200, {"ok": True}))

    def test_the_app_holds_its_settings_client_and_auth(self) -> None:
        settings = make_settings()
        http = self.injected_client()

        app = create_app(settings, http_client=http, title="Test module")

        self.assertEqual(app.title, "Test module")
        self.assertIs(app.state.settings, settings)
        self.assertIs(app.state.http, http)
        self.assertIsInstance(app.state.module_auth, ModuleAuth)
        self.assertIs(app.state.module_auth.settings, settings)
        self.assertIs(app.state.module_auth.http_client, http)

    def test_the_auth_router_is_under_api_auth(self) -> None:
        client = TestClient(create_app(make_settings(), http_client=self.injected_client()))

        self.assertEqual(client.get("/api/auth/status").json(), {"authenticated": False, "user": None})

    def test_settings_come_from_the_environment_when_none_are_given(self) -> None:
        environment = {
            "ENEO_BACKEND_URL": "http://backend:8000",
            "ENEO_PUBLIC_URL": "https://eneo.example.test",
            "MODULE_PUBLIC_URL": "https://module.example.test",
            "MODULE_KEY": "from-environment",
            "ENEO_API_KEY": "test-key",
            "SESSION_SECRET": "x" * 48,
        }
        with patch.dict(os.environ, environment, clear=True):
            app = create_app(http_client=self.injected_client())

        self.assertEqual(app.state.settings.module_key, "from-environment")

    def test_a_client_the_app_created_is_closed_on_shutdown(self) -> None:
        app = create_app(make_settings())
        created = app.state.http

        # It exists before the app starts: the auth router needs it at once.
        self.assertFalse(created.is_closed)
        self.assertIs(app.state.module_auth.http_client, created)
        self.assertEqual(created.timeout, httpx.Timeout(60.0, connect=10.0))
        self.assertFalse(created.follow_redirects)
        with TestClient(app):
            self.assertFalse(created.is_closed)
        self.assertTrue(created.is_closed)

    def test_an_injected_client_is_not_closed_by_the_app(self) -> None:
        injected = self.injected_client()

        with TestClient(create_app(make_settings(), http_client=injected)):
            pass

        self.assertFalse(injected.is_closed)

    def test_a_modules_routers_are_part_of_the_app(self) -> None:
        client = TestClient(create_app(make_settings(), routers=[module_router()], http_client=self.injected_client()))

        self.assertEqual(client.get("/api/mine").json(), {"own": "mine"})
        self.assertEqual(client.post("/api/eneo/things/1/files").json(), {"own": "1"})

    def test_a_router_cannot_replace_a_route_of_the_kit(self) -> None:
        async def taken_over() -> dict[str, bool]:
            return {"taken": True}

        router = APIRouter()
        for path in ("/health", "/api/healthz", "/api/auth/status", "/api/auth/callback", "/api/branding"):
            router.add_api_route(path, taken_over, methods=["GET"])
        client = TestClient(
            create_app(make_settings(), routers=[router], http_client=self.injected_client()),
            follow_redirects=False,
        )

        self.assertEqual(client.get("/health").json(), {"ok": True})
        self.assertEqual(client.get("/api/healthz").json(), {"ok": True})
        self.assertEqual(client.get("/api/auth/status").json(), {"authenticated": False, "user": None})
        self.assertEqual(client.get("/api/branding").json(), {"organization": None})
        # Without a login state the callback refuses and redirects; the module's route would have answered 200.
        self.assertEqual(client.get("/api/auth/callback").status_code, 303)

    def test_two_apps_share_no_state(self) -> None:
        first = create_app(make_settings(), http_client=self.injected_client())
        second = create_app(make_settings(), http_client=self.injected_client())

        self.assertIsNot(first.state.module_auth, second.state.module_auth)
        self.assertIsNot(first.state.module_auth.sessions, second.state.module_auth.sessions)
        self.assertIsNot(first.state.signed_urls, second.state.signed_urls)


if __name__ == "__main__":
    unittest.main()
