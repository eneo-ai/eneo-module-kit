import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_an_answer_under_api_is_not_cached_unless_its_route_says_how(self) -> None:
        router = APIRouter()

        @router.get("/api/plain")
        async def plain() -> dict[str, str]:
            return {"own": "plain"}

        @router.get("/api/cached")
        async def cached() -> Response:
            return Response("{}", headers={"Cache-Control": "max-age=60"})

        client = self.build(routers=[router])

        for path in ("/api/plain", "/api/nope", "/api/healthz", "/api", "/api/", "/api/branding", "/api/branding/logo/light"):
            with self.subTest(path):
                self.assertEqual(client.get(path).headers["cache-control"], "private, no-store")
        for path, own in (("/api/cached", "max-age=60"), ("/api/auth/status", "no-store"), ("/flows/abc", "no-cache")):
            with self.subTest(path):
                self.assertEqual(client.get(path).headers["cache-control"], own)
        for path in ("/health", "/assets/app.js", "/favicon.svg", "/assets/nope.js", "//api/plain"):
            with self.subTest(path):
                self.assertNotIn("no-store", client.get(path).headers.get("cache-control", ""))

    def test_an_unhandled_error_is_a_500_with_the_security_headers_and_is_still_raised_to_the_server(self) -> None:
        router = APIRouter()

        @router.get("/api/boom")
        async def api_boom() -> None:
            raise RuntimeError("a bug in a route")

        @router.get("/boom")
        async def boom() -> None:
            raise RuntimeError("a bug in a route")

        client = self.build(
            routers=[router], security_headers={"Permissions-Policy": "camera=(), geolocation=(), microphone=(self)"}
        )
        client = TestClient(client.app, raise_server_exceptions=False)

        for path, cache in (("/api/boom", "private, no-store"), ("/boom", None)):
            with self.subTest(path):
                response = client.get(path)

                self.assertEqual((response.status_code, response.text), (500, "Internal Server Error"))
                for name, value in SECURITY_HEADERS.items():
                    expected = "camera=(), geolocation=(), microphone=(self)" if name == "Permissions-Policy" else value
                    self.assertEqual(response.headers[name], expected, f"{name} on {path}")
                self.assertEqual(response.headers.get("cache-control"), cache)
        with self.assertRaises(RuntimeError):
            TestClient(client.app).get("/api/boom")

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


class StaticRuleTests(unittest.TestCase):
    """What serve_web answers for a path that names nothing, a file twice, or a file that must not be named."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name) / "dist"
        (self.root / "assets").mkdir(parents=True)
        (self.root / "index.html").write_text(INDEX)
        (self.root / "assets" / "app.js").write_text("console.log(1)")
        (self.root / "assets" / "app.css").write_text("body{}")
        (self.root / "assets" / "app.js.br").write_bytes(b"not really brotli")
        (self.root / "assets" / "app.js.gz").write_bytes(b"not really gzip")
        (self.root / "index.html.br").write_bytes(b"not really brotli")
        (self.root / "favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')
        (self.root / ".hidden").write_text("hidden-content")
        (self.root / "assets" / ".DS_Store").write_text("hidden-content")
        (Path(folder.name) / "secret.txt").write_text("secret")
        http = httpx2.AsyncClient()
        self.addCleanup(lambda: asyncio.run(http.aclose()))
        self.app = create_app(make_settings(), static_dir=self.root, http_client=http)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def not_found(self, response: httpx2.Response) -> None:
        self.assertEqual((response.status_code, response.json()), (404, {"detail": "Not Found"}))

    def raw_get(self, path: str) -> httpx2.Response:
        """A GET with ``path`` as the server receives it: the test client's URL parser reads ``//api/x`` as a host and
        resolves ``/./``, so a path that is not canonical goes to the app directly."""
        sent: list[dict] = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http", "root_path": "",
            "path": path, "raw_path": path.encode(), "query_string": b"", "headers": [(b"host", b"testserver")],
            "client": ("127.0.0.1", 1), "server": ("testserver", 80),
        }
        asyncio.run(self.app(scope, receive, send))
        start = next(message for message in sent if message["type"] == "http.response.start")
        body = b"".join(message.get("body", b"") for message in sent if message["type"] == "http.response.body")
        return httpx2.Response(start["status"], headers=start["headers"], content=body)

    def test_a_control_character_or_a_backslash_anywhere_in_the_path_is_a_404_json_never_the_page(self) -> None:
        for path in (
            "/%00", "/a%00", "/flows/%00", "/a%00.js", "/assets/a%00.js",  # NUL
            "/%01", "/flows/%1f", "/%0a", "/%0d", "/a%09b", "/flows/a%7f",  # the rest of C0, and DEL
            "/%5Cb", "/flows/a%5Cb", "/a%5Cb.js",  # a backslash
        ):
            with self.subTest(path=path):
                self.not_found(self.client.get(path))
        for path in ("/a%20b", "/fl%C3%B6de/%C3%A5", "/flows/abc"):  # a space, and letters outside ASCII, are names
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).text, INDEX)

    def test_a_path_that_is_not_canonical_is_never_the_page_in_place_of_an_api_404(self) -> None:
        for path in ("//api/x", "///api/x", "//api", "/./api/x", "/../api/x", "/a/../api/x", "/flows/./x", "/flows/../x"):
            with self.subTest(path=path):
                self.not_found(self.raw_get(path))
        self.assertEqual(self.raw_get("/flows/abc").text, INDEX)

    def test_a_dotfile_is_never_served(self) -> None:
        for path in ("/.hidden", "/assets/.DS_Store", "/.env", "/.git/config", "/assets/.hidden.js", "/a/.b"):
            with self.subTest(path=path):
                response = self.client.get(path)

                self.not_found(response)
                self.assertNotIn("hidden-content", response.text)

    def test_a_name_too_long_for_the_system_is_a_404_not_a_500(self) -> None:
        for path in ("/" + "a" * 5000 + ".js", "/assets/" + "a" * 5000 + ".js", "/assets/" + "a" * 300 + ".js", "/" + "a" * 5000 + ".png"):
            with self.subTest(path=path[:40] + f"…({len(path)})"):
                self.not_found(self.client.get(path))
        self.assertEqual(self.client.get("/" + "a" * 5000).text, INDEX, "a route of the app, however long, is the page")

    def test_head_is_answered_like_get_without_a_body(self) -> None:
        for path in ("/", "/flows/abc", "/index.html", "/assets/app.js", "/favicon.svg", "/health", "/api/healthz", "/assets/nope.js", "/api/nope"):
            with self.subTest(path=path):
                got, head = self.client.get(path), self.client.head(path)

                self.assertEqual(head.status_code, got.status_code)
                self.assertEqual(head.content, b"")
                self.assertEqual(head.headers.get("content-type"), got.headers.get("content-type"))
                self.assertEqual(head.headers.get("content-length"), got.headers.get("content-length"))

    def test_a_file_has_one_url_and_a_compressed_sibling_is_never_served_by_its_name(self) -> None:
        for path in ("/assets/app.js/", "/assets/app.css/", "/assets/app.js.br", "/assets/app.js.gz", "/assets/app.js.br/", "/assets/app.js.gz/", "/index.html.br", "/assets/"):
            with self.subTest(path=path):
                response = self.client.get(path)

                self.not_found(response)
                self.assertNotIn("not really", response.text)
        self.assertEqual(self.client.get("/assets/app.js").status_code, 200)
        # Outside assets/ a path that ends in a slash is a route of the app, as any other: the page, never a file.
        for path in ("/flows/", "/favicon.svg/", "/index.html.br/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).text, INDEX)

    def test_the_page_is_one_document_at_one_address(self) -> None:
        response = self.client.get("/index.html")

        self.assertEqual((response.status_code, response.text, response.headers["cache-control"]), (200, INDEX, "no-cache"))

    def test_a_file_that_is_reached_through_a_link_out_of_the_folder_is_not_served(self) -> None:
        (self.root / "link.txt").symlink_to(self.root.parent / "secret.txt")
        http = httpx2.AsyncClient()
        self.addCleanup(lambda: asyncio.run(http.aclose()))
        client = TestClient(create_app(make_settings(), static_dir=self.root, http_client=http), raise_server_exceptions=False)

        response = client.get("/link.txt")

        self.not_found(response)
        self.assertNotIn("secret", response.text)

    def test_the_folder_is_read_once_at_start_and_a_request_resolves_and_stats_nothing_to_find_a_file(self) -> None:
        with patch.object(Path, "resolve", side_effect=AssertionError("a request resolved a path")), patch.object(
            Path, "is_file", side_effect=AssertionError("a request asked the disk")
        ):
            self.assertEqual(self.client.get("/assets/app.js").status_code, 200)
            self.assertEqual(self.client.get("/favicon.svg").status_code, 200)
            self.not_found(self.client.get("/assets/nope.js"))
            self.not_found(self.client.get("/" + "a" * 5000 + ".js"))
            self.assertEqual(self.client.get("/flows/abc").text, INDEX)


if __name__ == "__main__":
    unittest.main()
