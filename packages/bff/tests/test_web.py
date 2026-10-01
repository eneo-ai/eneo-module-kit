import asyncio
import tempfile
import unittest
from pathlib import Path

import httpx2
from fastapi import APIRouter, Response
from fastapi.testclient import TestClient

from eneo_module_bff.app import create_app
from eneo_module_bff.settings import Settings
from eneo_module_bff.web import CONTENT_SECURITY_POLICY, SECURITY_HEADERS

INDEX = "<!doctype html><title>app</title><div id=root></div>"


def make_settings() -> Settings:
    return Settings(
        eneo_backend_url="https://eneo.example.test",
        eneo_public_url="https://eneo.example.test",
        module_public_url="https://module.example.test",
        module_key="test-module",
        eneo_api_key="test-key",
        session_secret="x" * 48,
        cookie_secure=False,
    )


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


class WebTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name) / "dist"
        (self.root / "assets").mkdir(parents=True)
        (self.root / "index.html").write_text(INDEX)
        (self.root / "assets" / "app.js").write_text("console.log(1)")
        (self.root / "favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')
        # Beside the built UI, not in it: nothing may reach this.
        (Path(folder.name) / "secret.txt").write_text("secret")
        self.client = self.build()

    def build(self, **kwargs: object) -> TestClient:
        http = httpx2.AsyncClient()
        self.addCleanup(lambda: asyncio.run(http.aclose()))
        return TestClient(create_app(make_settings(), static_dir=self.root, http_client=http, **kwargs))

    def test_the_page_answers_for_the_root_and_for_every_route_of_the_app(self) -> None:
        for path in ("/", "/flows/abc", "/a/b/c"):
            with self.subTest(path=path):
                response = self.client.get(path)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.text, INDEX)
                self.assertTrue(response.headers["content-type"].startswith("text/html"))
                self.assertEqual(response.headers["cache-control"], "no-cache")

    def test_api_itself_and_every_unknown_api_path_is_404_json_never_the_page(self) -> None:
        for path in ("/api", "/api/", "/api/nope", "/api/anything/unknown"):
            with self.subTest(path=path):
                response = self.client.get(path)

                self.assertEqual(response.status_code, 404)
                self.assertTrue(response.headers["content-type"].startswith("application/json"))
                self.assertEqual(response.json(), {"detail": "Not Found"})

    def test_a_modules_own_routes_win_over_the_page_fallback(self) -> None:
        client = self.build(routers=[module_router()])

        self.assertEqual(client.get("/api/mine").json(), {"own": "mine"})
        self.assertEqual(client.post("/api/eneo/things/1/files").json(), {"own": "1"})
        # The page and the unknown API paths are as before.
        self.assertEqual(client.get("/flows/abc").text, INDEX)
        self.assertEqual(client.get("/api/nope").status_code, 404)

    def test_files_that_exist_are_served_and_files_that_do_not_are_404_never_html(self) -> None:
        self.assertEqual(self.client.get("/assets/app.js").status_code, 200)
        self.assertEqual(self.client.get("/favicon.svg").status_code, 200)
        for path in ("/assets/nope.js", "/logo.png", "/some/dir/style.css"):
            with self.subTest(path=path):
                response = self.client.get(path)

                self.assertEqual(response.status_code, 404)
                self.assertNotIn("<title>", response.text)

    def test_an_unknown_api_path_is_404_with_json_not_the_page(self) -> None:
        response = self.client.get("/api/nope")

        self.assertEqual(response.status_code, 404)
        self.assertTrue(response.headers["content-type"].startswith("application/json"))
        self.assertEqual(response.json(), {"detail": "Not Found"})
        self.assertEqual(self.client.get("/api/auth/nope/deeper").status_code, 404)

    def test_a_path_cannot_leave_the_built_ui(self) -> None:
        for path in (
            "/../secret.txt",
            "/%2E%2E/secret.txt",
            "/..%2Fsecret.txt",
            "/%2E%2E%2Fsecret.txt",
            "/assets/%2E%2E/secret.txt",
            "/assets/..%2F..%2Fsecret.txt",
            "/x/%2E%2E/%2E%2E/secret.txt",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)

                self.assertNotIn("secret", response.text)
                self.assertIn(response.status_code, (404, 400))

    def test_every_response_carries_the_security_headers(self) -> None:
        self.assertEqual(
            set(SECURITY_HEADERS),
            {"Content-Security-Policy", "Referrer-Policy", "X-Content-Type-Options", "X-Frame-Options", "Permissions-Policy"},
        )
        for path in ("/", "/flows/abc", "/assets/app.js", "/assets/nope.js", "/favicon.svg", "/api/nope", "/health"):
            response = self.client.get(path)
            for name, value in SECURITY_HEADERS.items():
                self.assertEqual(response.headers[name], value, f"{name} on {path}")

    def test_the_policy_allows_nothing_inline_and_nothing_from_another_origin(self) -> None:
        self.assertIn("script-src 'self'", CONTENT_SECURITY_POLICY)
        self.assertIn("style-src 'self'", CONTENT_SECURITY_POLICY)
        self.assertNotIn("unsafe-inline", CONTENT_SECURITY_POLICY)
        self.assertNotIn("unsafe-eval", CONTENT_SECURITY_POLICY)
        self.assertIn("frame-ancestors 'none'", CONTENT_SECURITY_POLICY)

    def test_a_route_that_sets_its_own_header_keeps_it(self) -> None:
        app = create_app(make_settings(), http_client=httpx2.AsyncClient())

        @app.get("/api/preview")
        async def preview() -> Response:
            return Response("pdf", headers={"Content-Security-Policy": "frame-ancestors 'self'", "X-Frame-Options": "SAMEORIGIN"})

        response = TestClient(app).get("/api/preview")

        self.assertEqual(response.headers["content-security-policy"], "frame-ancestors 'self'")
        self.assertEqual(response.headers["x-frame-options"], "SAMEORIGIN")
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")

    def test_a_module_can_override_one_header(self) -> None:
        client = self.build(security_headers={"Permissions-Policy": "camera=(), geolocation=(), microphone=(self)"})

        response = client.get("/")

        self.assertEqual(response.headers["permissions-policy"], "camera=(), geolocation=(), microphone=(self)")
        for name, value in SECURITY_HEADERS.items():
            if name != "Permissions-Policy":
                self.assertEqual(response.headers[name], value)

    def test_without_a_static_dir_the_app_serves_no_page(self) -> None:
        client = TestClient(create_app(make_settings(), http_client=httpx2.AsyncClient()))

        self.assertEqual(client.get("/").status_code, 404)
        self.assertEqual(client.get("/health").json(), {"ok": True})
        self.assertEqual(client.get("/").headers["x-content-type-options"], "nosniff")


if __name__ == "__main__":
    unittest.main()
