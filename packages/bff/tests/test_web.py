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
        # An old build's file after a new release is one of these: a 404 that no cache keeps.
        for path in ("/assets/nope.js", "/assets/nope", "/logo.png", "/some/dir/style.css"):
            with self.subTest(path=path):
                response = self.client.get(path)

                self.assertEqual(response.status_code, 404)
                self.assertNotIn("<title>", response.text)
                self.assertNotIn("cache-control", response.headers)

    def test_a_hashed_file_is_kept_for_a_year_and_everything_else_is_asked_again(self) -> None:
        # Under /assets the build names each file by its content, so a new build has new names; the page and the files
        # beside it keep their names, and a new release must reach the next visit.
        for path, cache in (
            ("/assets/app.js", "public, max-age=31536000, immutable"),
            ("/", "no-cache"),
            ("/flows/abc", "no-cache"),
            ("/favicon.svg", "no-cache"),
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                etag = response.headers["etag"]

                self.assertEqual(response.headers["cache-control"], cache)
                again = self.client.get(path, headers={"If-None-Match": f'W/"other", {etag}'})
                self.assertEqual((again.status_code, again.content), (304, b""))
                self.assertEqual((again.headers["etag"], again.headers["cache-control"]), (etag, cache))
                self.assertEqual(again.headers["content-security-policy"], CONTENT_SECURITY_POLICY)
                self.assertEqual(self.client.get(path, headers={"If-None-Match": '"other"'}).status_code, 200)

    def raw(self, path: str, accept_encoding: str | None) -> tuple[httpx2.Response, bytes]:
        """The answer and its body as sent, not decoded."""
        with self.client.stream("GET", path, headers={"Accept-Encoding": accept_encoding or ""}) as response:
            return response, b"".join(response.iter_raw())

    def test_a_precompressed_file_is_sent_to_a_client_that_accepts_it_and_only_by_negotiation(self) -> None:
        (self.root / "assets" / "app.js.br").write_bytes(b"brotli of app.js")
        (self.root / "assets" / "app.js.gz").write_bytes(b"gzip of app.js")
        (self.root / "assets" / "app.css").write_text("a{}")
        (self.root / "assets" / "app.css.gz").write_bytes(b"gzip of app.css")
        etags = set()
        for path, accept, encoding, body in (
            ("/assets/app.js", "gzip, deflate, br, zstd", "br", b"brotli of app.js"),
            ("/assets/app.js", "gzip, deflate", "gzip", b"gzip of app.js"),
            ("/assets/app.js", "br;q=0, gzip;q=0.5", "gzip", b"gzip of app.js"),
            ("/assets/app.js", None, None, b"console.log(1)"),
            ("/assets/app.js", "identity", None, b"console.log(1)"),
            ("/assets/app.css", "br, gzip", "gzip", b"gzip of app.css"),
        ):
            with self.subTest(path=path, accept=accept):
                response, sent = self.raw(path, accept)

                self.assertEqual((response.status_code, sent, response.headers.get("content-encoding")), (200, body, encoding))
                self.assertEqual(response.headers["vary"], "Accept-Encoding")
                self.assertEqual(response.headers["content-type"].split(";")[0], "text/css" if path.endswith(".css") else "text/javascript")
                self.assertEqual(response.headers["cache-control"], "public, max-age=31536000, immutable")
                etags.add(response.headers["etag"])
                again = self.client.get(path, headers={"Accept-Encoding": accept or "", "If-None-Match": response.headers["etag"]})
                self.assertEqual((again.status_code, again.headers["vary"]), (304, "Accept-Encoding"))
        self.assertEqual(len(etags), 4, "each body of a file has its own ETag")
        self.assertNotIn("vary", self.client.get("/favicon.svg").headers, "a file the build did not compress")
        for path in ("/assets/app.js.br", "/assets/app.js.gz", "/assets/app.css.gz", "/assets/app.js.br/", "/assets/app.js.gz/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404, "a compressed body never goes out as a file of its own")

    def test_a_compressed_sibling_that_leads_out_of_the_built_ui_is_none(self) -> None:
        (self.root / "assets" / "app.js.br").symlink_to(self.root.parent / "secret.txt")

        response, sent = self.raw("/assets/app.js", "br, gzip")

        self.assertEqual((sent, response.headers.get("content-encoding")), (b"console.log(1)", None))
        self.assertNotIn("vary", response.headers)

    def test_head_is_answered_like_get_without_a_body(self) -> None:
        for path in ("/", "/flows/abc", "/assets/app.js", "/favicon.svg"):
            with self.subTest(path=path):
                head, get = self.client.head(path), self.client.get(path)

                self.assertEqual((head.status_code, head.content), (200, b""))
                for name in ("content-type", "content-length", "etag", "cache-control", "content-security-policy"):
                    self.assertEqual(head.headers[name], get.headers[name], name)

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

    def test_a_path_that_names_nothing_is_a_404_never_a_500_a_dotfile_or_the_page(self) -> None:
        # NUL made Path.resolve raise and a name too long made is_file raise: a 500 that anyone could provoke.
        (self.root / ".env").write_text("SECRET=1")
        (self.root / ".vite").mkdir()
        (self.root / ".vite" / "manifest.json").write_text('{"secret": 1}')
        (self.root / "assets" / ".hidden.js").write_text("secret")
        client = TestClient(self.client.app, raise_server_exceptions=False)
        for path in (
            "/x%00.js",
            "/x%01.js",
            "/x%7F",
            "/x%0A",
            "/a%5Cb.js",
            "/a%5Cb",
            "/a/%2E/b",
            "/a/%2E%2E/index.html",
            "/.env",
            "/.vite/manifest.json",
            "/assets/.hidden.js",
            "/assets/x%00.js",
            "/" + "a" * 300 + ".js",
        ):
            with self.subTest(path=path):
                response = client.get(path)

                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json(), {"detail": "Not Found"})
                self.assertEqual(response.headers["content-security-policy"], CONTENT_SECURITY_POLICY)

    def test_a_doubled_slash_never_turns_an_api_path_into_the_page(self) -> None:
        # The route's pattern drops one leading slash: //api/x reached the page as the path /api/x.
        for path in ("//api", "//api/x", "///api/eneo/flows/"):
            with self.subTest(path=path):
                response = self.client.get(f"http://testserver{path}")

                self.assertEqual(response.status_code, 404)
                self.assertNotIn("<title>", response.text)

    def test_every_response_carries_the_security_headers(self) -> None:
        self.assertEqual(
            set(SECURITY_HEADERS),
            {"Content-Security-Policy", "Referrer-Policy", "X-Content-Type-Options", "X-Frame-Options", "Permissions-Policy"},
        )
        for path in ("/", "/flows/abc", "/assets/app.js", "/assets/nope.js", "/favicon.svg", "/api/nope", "/health"):
            response = self.client.get(path)
            for name, value in SECURITY_HEADERS.items():
                self.assertEqual(response.headers[name], value, f"{name} on {path}")

    def test_an_unhandled_error_is_a_500_that_carries_the_security_headers(self) -> None:
        # Starlette answers it outside every middleware, so no middleware can add them to it.
        router = APIRouter()

        @router.get("/api/broken")
        async def broken() -> None:
            raise RuntimeError("boom")

        client = TestClient(self.build(routers=[router]).app, raise_server_exceptions=False)

        response = client.get("/api/broken")

        self.assertEqual((response.status_code, response.text), (500, "Internal Server Error"))
        for name, value in SECURITY_HEADERS.items():
            self.assertEqual(response.headers[name], value, name)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_an_api_answer_is_not_stored_unless_its_route_says_how(self) -> None:
        client = self.build(routers=[module_router()])

        self.assertEqual(client.get("/api/mine").headers["cache-control"], "no-store")
        self.assertEqual(client.get("/api/nope").headers["cache-control"], "no-store")
        self.assertEqual(client.get("/api/branding/theme.css").headers["cache-control"], "public, max-age=300")
        # Not under /api: the page revalidates, and the health check says nothing about caching.
        self.assertEqual(client.get("/flows/abc").headers["cache-control"], "no-cache")
        self.assertNotIn("cache-control", client.get("/health").headers)

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
        self.assertTrue(client.get("/health").json()["ok"])
        self.assertEqual(client.get("/").headers["x-content-type-options"], "nosniff")


if __name__ == "__main__":
    unittest.main()
