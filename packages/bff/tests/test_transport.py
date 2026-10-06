import asyncio
import logging
import time
import unittest

import anyio
import httpx2
from fastapi import Depends, Request, Response
from fastapi.testclient import TestClient

from eneo_module_bff.app import create_app
from eneo_module_bff.auth import SESSION_COOKIE, ModuleSession, ModuleUser
from eneo_module_bff.deps import require_same_origin, require_session
from eneo_module_bff import heavy_io_slot
from eneo_module_bff.settings import Settings
from eneo_module_bff.transport import (
    _rebase_signed_url,
    _requested_upload_timeout_seconds,
    _upload_timeout,
    forward_upload,
    stream_signed,
)

SIGNED = "https://eneo.example.test/api/v1/files/file-1/download/?token=abc"
MINT_PATH = "flows/flow-1/runs/run-1/input-files/file-1/signed-url/"
ORIGIN = {"Origin": "https://module.example.test"}


def make_settings(**overrides: object) -> Settings:
    return Settings(
        eneo_backend_url="https://eneo.example.test",
        eneo_public_url="https://eneo.example.test",
        module_public_url="https://module.example.test",
        module_key="speech-to-text",
        eneo_api_key="test-key",
        session_secret="x" * 48,
        cookie_secure=False,
        **overrides,
    )


def module_session() -> ModuleSession:
    return ModuleSession(
        access_token="module-user-token",
        expires_at=int(time.time()) + 60,
        refresh_at=int(time.time()) + 30,
        session_expires_at=int(time.time()) + 3600,
        module_key="speech-to-text",
        tenant_id="tenant-id",
        user=ModuleUser(id="user-id", email="user@example.test"),
    )


class TransportFixture:
    """A module's app: create_app plus the two routes a module writes around the kit's functions."""

    def build(self, http_client, **settings: object) -> None:
        self.app = create_app(make_settings(**settings), http_client=http_client)

        @self.app.post(
            "/upload/{flow_id}",
            dependencies=[Depends(require_session), Depends(require_same_origin)],
        )
        async def upload(flow_id: str, request: Request) -> Response:
            # No File(...) here: forward_upload reads the body, after the dependencies above have run.
            return await forward_upload(request, f"flows/{flow_id}/files/")

        @self.app.get(
            "/audio/{flow_id}/{run_id}/{file_id}",
            dependencies=[Depends(require_session)],
        )
        async def audio(flow_id: str, run_id: str, file_id: str, request: Request) -> Response:
            return await stream_signed(
                request,
                flow_id,
                run_id,
                file_id,
                mint_path=f"flows/{flow_id}/runs/{run_id}/input-files/{file_id}/signed-url/",
                unavailable="Audio is not available for this run.",
            )

        @self.app.get(
            "/notes/{flow_id}/{run_id}/{file_id}",
            dependencies=[Depends(require_session)],
        )
        async def notes(flow_id: str, run_id: str, file_id: str, request: Request) -> Response:
            return await stream_signed(
                request,
                flow_id,
                run_id,
                file_id,
                mint_path=f"flows/{flow_id}/runs/{run_id}/input-files/{file_id}/signed-url/",
                unavailable="The note is not available.",
                inline_types=["text/plain", "image/*"],
            )

        self.client = TestClient(self.app)
        self.session_id = self.store.create(module_session())
        self.client.cookies.set(SESSION_COOKIE, self.session_id)

    @property
    def store(self):
        return self.app.state.module_auth.sessions

    def cached(self) -> dict:
        """Every signed URL the store holds, by session: they live and die with the sessions."""
        return self.store._signed_urls

    def upload_file(self, flow_id: str = "flow", **kwargs):
        return self.client.post(
            f"/upload/{flow_id}",
            headers={**ORIGIN, **kwargs.pop("headers", {})},
            files={"upload_file": ("meeting.webm", b"audio", "audio/webm")},
            **kwargs,
        )


class UploadTimeoutTests(unittest.TestCase):
    def test_upload_timeout_uses_configured_default(self) -> None:
        timeout = _upload_timeout(make_settings())

        self.assertEqual(timeout.read, 1800.0)
        self.assertEqual(timeout.write, 1800.0)
        self.assertEqual(timeout.connect, 10.0)
        self.assertEqual(timeout.pool, 30.0)

    def test_upload_timeout_follows_the_page_budget_for_eneos_answer(self) -> None:
        request = Request({"type": "http", "headers": [(b"x-upload-timeout-seconds", b"600")]})

        timeout = _upload_timeout(make_settings(), _requested_upload_timeout_seconds(request))

        self.assertEqual(timeout.read, 600.0)

    def test_upload_timeout_clamps_client_budget(self) -> None:
        too_low = _upload_timeout(make_settings(), 30.0)
        too_high = _upload_timeout(make_settings(), 99_999.0)

        self.assertEqual(too_low.read, 60.0)
        self.assertEqual(too_low.write, 60.0)
        self.assertEqual(too_high.read, 1800.0)
        self.assertEqual(too_high.write, 1800.0)


class FakeHttpClient:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self.url = None
        self.files = None
        self.headers = None
        self.timeout = None
        self.body = None

    async def post(self, url, **kwargs):
        self.url = url
        self.files = kwargs["files"]
        self.headers = kwargs["headers"]
        self.timeout = kwargs["timeout"]
        self.body = self.files["upload_file"][1].read()

        class FakeResponse:
            content = b'{"id":"file"}'
            headers = {"content-type": "application/json", "location": "http://eneo.internal/elsewhere/"}

        FakeResponse.status_code = self.status_code
        return FakeResponse()


class RaisingHttpClient:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls = 0

    async def post(self, *args, **kwargs):
        self.calls += 1
        raise self.exc


class UploadProxyTests(TransportFixture, unittest.TestCase):
    def test_proxy_upload_passes_file_stream_without_reading_bytes(self) -> None:
        client = FakeHttpClient()
        self.build(client)

        response = self.upload_file(headers={"X-Upload-Timeout-Seconds": "120"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"id": "file"})
        self.assertEqual(client.url, "https://eneo.example.test/api/v1/flows/flow/files/")
        assert client.files is not None
        filename, file_obj, content_type = client.files["upload_file"]
        self.assertEqual(filename, "meeting.webm")
        self.assertFalse(isinstance(file_obj, bytes), "the file is passed on as a stream, not as its bytes")
        self.assertEqual(client.body, b"audio", "rewound to the start")
        self.assertEqual(content_type, "audio/webm")
        self.assertEqual(client.headers["X-API-Key"], "test-key")
        self.assertEqual(
            client.headers["Authorization"],
            "Bearer module-user-token",
        )
        self.assertEqual(client.timeout.read, 120.0)

    def test_a_redirect_from_eneo_is_a_502_for_an_upload_too(self) -> None:
        self.build(FakeHttpClient(status_code=302))

        response = self.upload_file()

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"], "upstream_redirect")
        self.assertNotIn("location", response.headers)

    def test_proxy_upload_maps_upstream_timeout_to_504(self) -> None:
        self.build(RaisingHttpClient(httpx2.TimeoutException("stalled")))

        with self.assertLogs("eneo_proxy", level="ERROR"):
            response = self.upload_file()

        self.assertEqual(response.status_code, 504)

    def test_proxy_upload_maps_upstream_request_error_to_502(self) -> None:
        self.build(RaisingHttpClient(httpx2.ConnectError("unreachable")))

        with self.assertLogs("eneo_proxy", level="ERROR"):
            response = self.upload_file()

        self.assertEqual(response.status_code, 502)

    def test_an_upload_path_that_leaves_its_route_is_refused_before_eneo_is_called(self) -> None:
        client = RaisingHttpClient(httpx2.ConnectError("must not be called"))
        self.build(client)

        # %2E%2E decodes to a dot segment; a decoded "?" or "#" would move the rest of the path into a query.
        for flow_id in ("%2E%2E", "%2E", "x%3F", "x%23"):
            response = self.upload_file(flow_id)
            self.assertEqual(response.status_code, 403, flow_id)
            self.assertEqual(response.json(), {"detail": "Eneo resource is not exposed"})
        self.assertEqual(client.calls, 0)

    def test_a_control_character_or_a_backslash_in_an_upload_id_is_refused_before_eneo_is_called(self) -> None:
        client = RaisingHttpClient(httpx2.ConnectError("must not be called"))
        self.build(client)

        for flow_id in ("a%00b", "a%0Db", "a%0Ab", "a%7Fb", "a%5Cb"):
            response = self.upload_file(flow_id)
            self.assertEqual(response.status_code, 403, flow_id)
        self.assertEqual(client.calls, 0)

    def test_an_upload_needs_a_session_and_the_modules_origin(self) -> None:
        client = RaisingHttpClient(httpx2.ConnectError("must not be called"))
        self.build(client)

        cross_origin = self.upload_file(headers={"Origin": "https://attacker.example.test"})
        self.client.cookies.clear()
        anonymous = self.upload_file()

        self.assertEqual(cross_origin.status_code, 403)
        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(client.calls, 0)


NOT_JSON = object()


class FakeSignedUrlResponse:
    def __init__(self, status_code: int = 200, payload: object = None) -> None:
        self.status_code = status_code
        self.payload = payload

    def json(self):
        if self.status_code != 200:
            return {"code": "file_unavailable"}
        if self.payload is NOT_JSON:
            raise ValueError("not JSON")
        if self.payload is not None:
            return self.payload
        return {"url": SIGNED, "expires_at": int(time.time()) + 900}


class FakeStreamResponse:
    def __init__(self, status_code: int, headers: dict[str, str], body: bytes, hold: asyncio.Event | None = None) -> None:
        self.status_code = status_code
        self.headers = httpx2.Headers(headers)
        self._body = body
        self.hold = hold
        self.closed = False

    async def aiter_raw(self):
        yield self._body
        if self.hold is not None:
            await self.hold.wait()  # the file is not at its end until the test says so

    async def aread(self):
        return self._body

    async def aclose(self):
        self.closed = True


class FakeAudioClient:
    def __init__(self) -> None:
        self.signed_url_calls: list[dict[str, object]] = []
        self.stream_requests: list[httpx2.Request] = []
        self.stream_responses: list[FakeStreamResponse] = []
        self.mint_status = 200
        self.mint_payload: object = None
        self.stream_status = 200
        self.mint_error: Exception | None = None
        self.stream_error: Exception | None = None
        self.content_type: str | None = "audio/webm"
        self.disposition: str | None = None
        self.hold: asyncio.Event | None = None

    async def post(self, url, **kwargs):
        self.signed_url_calls.append({"url": url, **kwargs})
        if self.mint_error is not None:
            raise self.mint_error
        return FakeSignedUrlResponse(self.mint_status, self.mint_payload)

    def build_request(self, method, url, headers=None, extensions=None):
        return httpx2.Request(method, url, headers=headers, extensions=extensions)

    async def send(self, request, stream=False):
        self.stream_requests.append(request)
        if self.stream_error is not None:
            raise self.stream_error
        response = self.respond(request)
        self.stream_responses.append(response)
        return response

    def respond(self, request) -> FakeStreamResponse:
        if 300 <= self.stream_status < 400:
            return FakeStreamResponse(
                self.stream_status,
                {"location": "http://eneo.internal/elsewhere/", "content-type": "text/html"},
                b"",
            )
        if self.stream_status >= 400:
            return FakeStreamResponse(
                self.stream_status,
                {"content-type": "application/json"},
                b'{"detail": "The link has expired."}',
            )
        if "range" in request.headers:
            return FakeStreamResponse(
                206,
                self.file_headers(
                    {
                        "content-range": "bytes 0-3/10",
                        "content-length": "4",
                        "accept-ranges": "bytes",
                        "set-cookie": "leak=1",
                    }
                ),
                b"abcd",
            )
        return FakeStreamResponse(200, self.file_headers({"content-length": "10"}), b"0123456789", self.hold)

    def file_headers(self, headers: dict[str, str]) -> dict[str, str]:
        if self.content_type is not None:
            headers["content-type"] = self.content_type
        if self.disposition is not None:
            headers["content-disposition"] = self.disposition
        return headers


AUDIO = "/audio/flow-1/run-1/file-1"


class SignedFileStreamTests(TransportFixture, unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeAudioClient()
        self.build(self.fake)

    def test_rebase_signed_url_keeps_path_and_token(self) -> None:
        self.assertEqual(
            _rebase_signed_url(SIGNED, "http://eneo-backend:8000"),
            "http://eneo-backend:8000/api/v1/files/file-1/download/?token=abc",
        )

    def test_audio_is_streamed_with_range_and_module_credentials(self) -> None:
        response = self.client.get(
            AUDIO,
            headers={"Range": "bytes=0-3"},
        )

        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, b"abcd")
        self.assertEqual(response.headers["content-range"], "bytes 0-3/10")
        self.assertEqual(response.headers["accept-ranges"], "bytes")
        self.assertNotIn("set-cookie", response.headers)

        # Signed URL minted upstream with the module's credentials, inline.
        self.assertEqual(len(self.fake.signed_url_calls), 1)
        call = self.fake.signed_url_calls[0]
        self.assertEqual(
            call["url"],
            "https://eneo.example.test/api/v1/flows/flow-1/runs/run-1/input-files/file-1/signed-url/",
        )
        self.assertEqual(call["json"]["content_disposition"], "inline")
        headers = call["headers"]
        self.assertEqual(headers["X-API-Key"], "test-key")
        self.assertEqual(headers["Authorization"], "Bearer module-user-token")

        # The stream fetch kept the signed path and token and forwarded Range.
        stream_request = self.fake.stream_requests[0]
        self.assertEqual(
            str(stream_request.url),
            "https://eneo.example.test/api/v1/files/file-1/download/?token=abc",
        )
        self.assertEqual(stream_request.headers["range"], "bytes=0-3")

    def test_signed_url_is_reused_across_range_requests(self) -> None:
        for _ in range(3):
            self.client.get(
                AUDIO,
                headers={"Range": "bytes=0-3"},
            )
        self.assertEqual(len(self.fake.signed_url_calls), 1)
        self.assertEqual(len(self.fake.stream_requests), 3)

    def test_audio_route_rejects_dot_segments(self) -> None:
        response = self.client.get(
            "/audio/flow-1/%2E%2E/file-1",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.fake.signed_url_calls, [])

    def test_audio_route_requires_session(self) -> None:
        anonymous = TestClient(self.app)
        response = anonymous.get(
            AUDIO,
        )
        self.assertEqual(response.status_code, 401)

    def test_an_id_cannot_carry_a_query_or_fragment_into_the_mint_path(self) -> None:
        for run_id in ("run%3F1", "run%231"):
            response = self.client.get(f"/audio/flow-1/{run_id}/file-1")
            self.assertEqual(response.status_code, 403, run_id)
        self.assertEqual(self.fake.signed_url_calls, [])

    def test_a_control_character_or_a_backslash_in_an_id_is_refused_before_a_url_is_minted(self) -> None:
        for run_id in ("run%001", "run%0D1", "run%0A1", "run%7F1", "run%5C1"):
            response = self.client.get(f"/audio/flow-1/{run_id}/file-1")
            self.assertEqual(response.status_code, 403, run_id)
        self.assertEqual(self.fake.signed_url_calls, [])

    def test_a_streamed_file_is_never_kept_by_a_browser_or_a_proxy(self) -> None:
        response = self.client.get(AUDIO)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"0123456789")
        self.assertEqual(response.headers["cache-control"], "private, no-store")

    def test_a_file_that_could_run_in_the_modules_origin_is_never_shown_inline(self) -> None:
        # Eneo is asked for inline, and a user's upload decides its own content type: only the types that
        # cannot run script are shown inline from the module's origin.
        for content_type in (
            "text/html; charset=utf-8",
            "Text/HTML",
            "image/svg+xml",
            "application/xhtml+xml",
            "application/javascript",
            "application/octet-stream",
            "text/plain",
            None,
        ):
            with self.subTest(content_type=content_type):
                self.fake.content_type = content_type
                self.fake.disposition = "inline"

                response = self.client.get(AUDIO)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["content-disposition"], "attachment")
                self.assertEqual(response.headers["x-content-type-options"], "nosniff")

    def test_a_refused_inline_file_keeps_eneos_file_name(self) -> None:
        self.fake.content_type = "text/html"
        self.fake.disposition = 'inline; filename="rapport.html"'

        response = self.client.get(AUDIO)

        self.assertEqual(response.headers["content-disposition"], 'attachment; filename="rapport.html"')

    def test_audio_video_pdf_and_common_images_are_shown_inline_as_eneo_sent_them(self) -> None:
        for content_type in (
            "audio/webm",
            "audio/mpeg",
            "video/mp4",
            "application/pdf",
            "image/png",
            "image/jpeg",
            "image/gif",
            "image/webp",
            "AUDIO/WebM; codecs=opus",
        ):
            with self.subTest(content_type=content_type):
                self.fake.content_type = content_type
                self.fake.disposition = 'inline; filename="a"'

                response = self.client.get(AUDIO)

                self.assertEqual(response.headers["content-disposition"], 'inline; filename="a"')
                self.assertEqual(response.headers["x-content-type-options"], "nosniff")

    def test_audio_with_a_range_is_inline_and_206(self) -> None:
        self.fake.disposition = "inline"

        response = self.client.get(AUDIO, headers={"Range": "bytes=0-3"})

        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.headers["content-range"], "bytes 0-3/10")
        self.assertEqual(response.headers["content-disposition"], "inline")

    def test_the_module_does_not_invent_a_disposition_for_a_safe_file(self) -> None:
        response = self.client.get(AUDIO)

        self.assertNotIn("content-disposition", response.headers)

    def test_a_module_can_widen_what_is_shown_inline_but_only_by_what_it_names(self) -> None:
        for content_type, inline in (
            ("text/plain", True),
            ("image/svg+xml", True),  # "image/*" is the module's own choice
            ("text/html", False),
            ("application/javascript", False),
        ):
            with self.subTest(content_type=content_type):
                self.fake.content_type = content_type
                self.fake.disposition = "inline"

                response = self.client.get("/notes/flow-1/run-1/file-1")

                self.assertEqual(response.headers["content-disposition"], "inline" if inline else "attachment")

    def test_only_range_if_range_and_accept_reach_the_signed_url(self) -> None:
        # The signed URL is the credential; the browser's own are never sent to it.
        self.client.get(
            AUDIO,
            headers={
                "Range": "bytes=0-3",
                "If-Range": '"abc"',
                "Accept": "audio/webm",
                "Authorization": "Bearer browser-controlled-token",
                "X-API-Key": "browser-controlled-key",
            },
        )

        forwarded = {name.lower() for name in self.fake.stream_requests[0].headers}
        self.assertEqual({"range", "if-range", "accept"} & forwarded, {"range", "if-range", "accept"})
        for name in ("cookie", "authorization", "x-api-key"):
            self.assertNotIn(name, forwarded)

    def test_a_rejected_signed_url_is_dropped_and_the_next_request_mints_a_new_one(self) -> None:
        self.client.get(AUDIO)
        self.assertIsNotNone(self.store.signed_url(self.session_id, MINT_PATH))

        self.fake.stream_status = 403
        rejected = self.client.get(AUDIO)

        self.assertEqual(rejected.status_code, 403)
        self.assertIsNone(self.store.signed_url(self.session_id, MINT_PATH))
        self.assertEqual(self.cached(), {})
        self.assertTrue(self.fake.stream_responses[-1].closed)

        self.fake.stream_status = 200
        again = self.client.get(AUDIO)

        self.assertEqual(again.status_code, 200)
        self.assertEqual(len(self.fake.signed_url_calls), 2)

    def test_a_redirect_from_the_signed_url_is_a_502_and_the_url_is_not_kept(self) -> None:
        self.fake.stream_status = 302

        with self.assertLogs("eneo_proxy", level="ERROR"):
            response = self.client.get(AUDIO)

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"], "upstream_redirect")
        self.assertNotIn("location", response.headers)
        self.assertTrue(self.fake.stream_responses[-1].closed)
        self.fake.stream_status = 200
        self.assertEqual(self.client.get(AUDIO).status_code, 200)
        self.assertEqual(len(self.fake.signed_url_calls), 2, "the next request mints a new URL")

    def test_each_session_has_its_own_signed_url(self) -> None:
        self.client.get(AUDIO)
        other = TestClient(self.app)
        other.cookies.set(SESSION_COOKIE, self.app.state.module_auth.sessions.create(module_session()))

        other.get(AUDIO)

        self.assertEqual(len(self.fake.signed_url_calls), 2)
        self.assertEqual(len(self.cached()), 2, "one entry per session")

    def test_a_malformed_signed_url_answer_is_a_502_never_a_500(self) -> None:
        secret = {"secret": "SECRET-BODY-TOKEN"}
        for label, payload in (
            ("no url", {**secret}),
            ("url is null", {**secret, "url": None}),
            ("url is a number", {**secret, "url": 123}),
            ("url is a list", {**secret, "url": [SIGNED]}),
            ("url is empty", {**secret, "url": ""}),
            ("expires_at is words", {**secret, "url": SIGNED, "expires_at": "soon"}),
            ("expires_at is a date", {**secret, "url": SIGNED, "expires_at": "2026-10-01T12:00:00Z"}),
            ("expires_at is a list", {**secret, "url": SIGNED, "expires_at": [1]}),
            ("expires_at is true", {**secret, "url": SIGNED, "expires_at": True}),
            ("expires_at is NaN", {**secret, "url": SIGNED, "expires_at": float("nan")}),
            ("expires_at is infinite", {**secret, "url": SIGNED, "expires_at": float("inf")}),
            ("not JSON", NOT_JSON),
            ("a list, not an object", [SIGNED]),
            ("a string", "SECRET-BODY-TOKEN"),
            ("ftp", {**secret, "url": "ftp://eneo.example.test/api/v1/files/f/"}),
            ("file", {**secret, "url": "file:///etc/passwd"}),
            ("javascript", {**secret, "url": "javascript:alert(1)"}),
            ("relative", {**secret, "url": "/api/v1/files/f/download/?token=abc"}),
            ("no host", {**secret, "url": "http:///api/v1/files/f/"}),
        ):
            with self.subTest(label), self.assertLogs("eneo_proxy", level="ERROR") as logs:
                self.fake.mint_payload = payload

                response = self.client.get(AUDIO)

                self.assertEqual(response.status_code, 502)
                self.assertEqual(
                    response.json(),
                    {"error": "upstream_invalid", "detail": "Eneo answered with something the module cannot use."},
                )
                self.assertEqual(self.fake.stream_requests, [])
                # The log says which mint path, and never what was in the answer.
                self.assertIn("flows/flow-1/runs/run-1/input-files/file-1/signed-url/", logs.output[0])
                self.assertNotIn("SECRET-BODY-TOKEN", "\n".join(logs.output))
        self.assertEqual(self.cached(), {})

    def test_a_usable_signed_url_answer_is_still_taken_in_every_form_it_can_have(self) -> None:
        soon = int(time.time()) + 900
        for label, payload in (
            ("no expires_at", {"url": SIGNED}),
            ("null expires_at", {"url": SIGNED, "expires_at": None}),
            ("integer", {"url": SIGNED, "expires_at": soon}),
            ("float", {"url": SIGNED, "expires_at": float(soon)}),
            ("a number as text", {"url": SIGNED, "expires_at": str(soon)}),
            ("https", {"url": SIGNED.replace("https", "http"), "expires_at": soon}),
        ):
            with self.subTest(label):
                self.store.forget_signed_url(self.session_id, MINT_PATH)
                self.fake.mint_payload = payload

                self.assertEqual(self.client.get(AUDIO).status_code, 200)

    def test_logging_out_drops_the_signed_urls_of_that_session_and_only_that_one(self) -> None:
        self.client.get(AUDIO)
        other = TestClient(self.app)
        other_id = self.store.create(module_session())
        other.cookies.set(SESSION_COOKIE, other_id)
        other.get(AUDIO)
        self.assertEqual(set(self.cached()), {self.session_id, other_id})

        logout = self.client.post("/api/auth/logout", headers=ORIGIN)

        self.assertEqual(logout.status_code, 200)
        self.assertEqual(set(self.cached()), {other_id}, "a bearer URL to a file must not outlive the login that minted it")
        self.assertIsNone(self.store.signed_url(self.session_id, MINT_PATH))
        self.assertIsNotNone(self.store.signed_url(other_id, MINT_PATH))

    def test_a_session_that_ends_while_a_url_is_being_minted_leaves_no_entry(self) -> None:
        original_post = self.fake.post

        async def post_then_log_out(url, **kwargs):
            response = await original_post(url, **kwargs)
            self.store.delete(self.session_id)  # the logout arrives while Eneo is answering
            return response

        self.fake.post = post_then_log_out

        self.client.get(AUDIO)

        self.assertEqual(self.cached(), {})

    def test_eneo_refusing_the_file_passes_through_without_a_stream(self) -> None:
        self.fake.mint_status = 410

        response = self.client.get(AUDIO)

        self.assertEqual(response.status_code, 410)
        self.assertEqual(self.fake.stream_requests, [])
        self.assertEqual(self.cached(), {})

    def test_eneo_not_answering_is_a_502_when_minting_and_when_streaming(self) -> None:
        self.fake.mint_error = httpx2.ConnectError("unreachable")
        with self.assertLogs("eneo_proxy", level="ERROR"):
            minting = self.client.get(AUDIO)
        self.assertEqual((minting.status_code, minting.json()), (502, {"detail": "Eneo could not be reached."}))

        self.fake.mint_error = None
        self.fake.stream_error = httpx2.ReadTimeout("stalled")
        with self.assertLogs("eneo_proxy", level="ERROR"):
            streaming = self.client.get(AUDIO)
        self.assertEqual(
            (streaming.status_code, streaming.json()),
            (502, {"error": "upstream_unreachable", "detail": "Eneo could not be reached."}),
        )



class StreamSlotTests(TransportFixture, unittest.IsolatedAsyncioTestCase):
    """At most max_concurrent_streams files stream at once; the rest are 503, so the pool keeps room for the API."""

    LIMIT = 3

    async def asyncSetUp(self) -> None:
        self.fake = FakeAudioClient()
        self.fake.hold = asyncio.Event()
        self.build(self.fake, max_concurrent_streams=self.LIMIT)
        self.slots = self.app.state.stream_slots
        self.client = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=self.app), base_url="https://module.example.test", cookies={SESSION_COOKIE: self.session_id}
        )
        self.addAsyncCleanup(self.client.aclose)

    def free(self) -> int:
        return self.slots._value

    async def held(self, count: int) -> list[asyncio.Task]:
        """``count`` streams that are open and not finished: each holds a slot until the test releases them."""
        tasks = [asyncio.create_task(self.client.get(AUDIO)) for _ in range(count)]
        for _ in range(200):
            if self.free() == self.LIMIT - count:
                break
            await asyncio.sleep(0.01)
        return tasks

    async def test_a_stream_over_the_limit_is_503_with_retry_after_while_the_api_keeps_answering(self) -> None:
        tasks = await self.held(self.LIMIT)
        self.assertEqual(self.free(), 0)

        busy = await self.client.get(AUDIO)
        api = await self.client.get("/api/auth/status")

        self.assertEqual(busy.status_code, 503)
        self.assertEqual(busy.headers["retry-after"], "2")
        self.assertEqual(busy.json(), {"error": "streams_busy", "detail": "Too many files are being streamed. Try again shortly."})
        self.assertEqual(api.status_code, 200, "the slots a stream does not take are the API's")
        self.fake.hold.set()
        self.assertEqual([r.status_code for r in await asyncio.gather(*tasks)], [200] * self.LIMIT)
        self.assertEqual(self.free(), self.LIMIT)

    async def test_the_limit_is_checked_before_anything_is_minted(self) -> None:
        tasks = await self.held(self.LIMIT)
        minted = len(self.fake.signed_url_calls)

        await self.client.get("/audio/flow-1/run-2/file-2")

        self.assertEqual(len(self.fake.signed_url_calls), minted)
        self.fake.hold.set()
        await asyncio.gather(*tasks)

    async def test_a_slot_is_free_again_as_soon_as_a_stream_ends(self) -> None:
        self.fake.hold.set()  # files that end at once

        for _ in range(self.LIMIT * 3):
            self.assertEqual((await self.client.get(AUDIO)).status_code, 200)

        self.assertEqual(self.free(), self.LIMIT)

    async def test_a_stream_that_cannot_start_takes_no_slot(self) -> None:
        self.fake.hold.set()
        logging.disable(logging.CRITICAL)  # some of these are logged as errors, some are not: only the slot matters here
        self.addCleanup(logging.disable, logging.NOTSET)
        for label, setup in {
            "mint refused": lambda: setattr(self.fake, "mint_status", 410),
            "mint unreachable": lambda: setattr(self.fake, "mint_error", httpx2.ConnectError("down")),
            "mint answer unusable": lambda: setattr(self.fake, "mint_payload", {}),
            "file refused": lambda: setattr(self.fake, "stream_status", 403),
            "file redirected": lambda: setattr(self.fake, "stream_status", 302),
            "file unreachable": lambda: setattr(self.fake, "stream_error", httpx2.ReadTimeout("stalled")),
        }.items():
            with self.subTest(label):
                self.fake.mint_status, self.fake.mint_error, self.fake.mint_payload = 200, None, None
                self.fake.stream_status, self.fake.stream_error = 200, None
                self.store.forget_signed_url(self.session_id, MINT_PATH)
                setup()

                response = await self.client.get(AUDIO)

                self.assertGreaterEqual(response.status_code, 400)
                self.assertEqual(self.free(), self.LIMIT)
        with self.subTest("a path that leaves its route"):
            self.assertEqual((await self.client.get("/audio/flow-1/%2E%2E/file-1")).status_code, 403)
            self.assertEqual(self.free(), self.LIMIT)

    async def test_two_hundred_streams_that_are_cut_off_leave_no_slot_taken(self) -> None:
        for round_ in range(200):
            await self.cut_off(round_ % 2 == 0)

        self.assertEqual(self.free(), self.LIMIT, "a client that goes away must give its slot back, collected garbage or not")
        self.assertEqual((await self.client.get("/api/auth/status")).status_code, 200)

    async def cut_off(self, by_failed_send: bool) -> None:
        """One stream, fed straight to the app, that the client abandons: its connection breaks, or the request is cancelled."""
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "https", "path": "/audio/flow-1/run-1/file-1",
            "raw_path": b"/audio/flow-1/run-1/file-1", "query_string": b"", "root_path": "", "client": ("127.0.0.1", 1), "server": ("module.example.test", 443),
            "headers": [(b"cookie", f"{SESSION_COOKIE}={self.session_id}".encode())],
        }
        started = asyncio.Event()
        answered = 0

        async def receive():
            await asyncio.Event().wait()  # a GET has no body, and the client never says it is gone

        async def send(message) -> None:
            nonlocal answered
            if message["type"] == "http.response.body":
                answered += 1
                started.set()
                if by_failed_send:
                    raise OSError("client disconnected")

        task = asyncio.create_task(self.app(scope, receive, send))
        try:
            await asyncio.wait_for(started.wait(), 5)
            if not by_failed_send:
                task.cancel()
            await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 5)
        finally:
            if not task.done():
                task.cancel()

    async def test_the_default_limit_is_64_and_the_65th_stream_is_refused(self) -> None:
        fake = FakeAudioClient()
        fake.hold = asyncio.Event()
        self.build(fake)  # the default
        client = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=self.app), base_url="https://module.example.test", cookies={SESSION_COOKIE: self.session_id}
        )
        self.addAsyncCleanup(client.aclose)
        tasks = [asyncio.create_task(client.get(AUDIO)) for _ in range(64)]
        for _ in range(300):
            if self.app.state.stream_slots.locked():
                break
            await asyncio.sleep(0.01)

        refused = await client.get(AUDIO)

        self.assertEqual(refused.status_code, 503)
        fake.hold.set()
        self.assertEqual({r.status_code for r in await asyncio.gather(*tasks)}, {200})


class HeavyIOAdmissionTests(TransportFixture, unittest.IsolatedAsyncioTestCase):
    async def test_cancelling_a_refused_file_closes_its_upstream_before_releasing_capacity(self) -> None:
        reading = anyio.Event()
        closed = False

        class Refused(FakeAudioClient):
            async def send(self, *args, **kwargs):
                response = FakeStreamResponse(403, {"content-type": "application/json"}, b"{}")

                async def raw():
                    yield b"{"
                    reading.set()
                    await anyio.sleep_forever()

                async def close():
                    nonlocal closed
                    await anyio.sleep(0)
                    closed = True

                response.aiter_raw = raw
                response.aclose = close
                return response

        self.build(Refused(), max_concurrent_heavy_io=1)
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=self.app), base_url="https://module.example.test",
                                     cookies={SESSION_COOKIE: self.session_id}) as browser:
            async with anyio.create_task_group() as group:
                group.start_soon(browser.get, AUDIO)
                with anyio.fail_after(2):
                    await reading.wait()
                group.cancel_scope.cancel()
        self.assertTrue(closed, "a cancelled error response must close its HTTP connection")
        self.assertEqual(self.app.state.heavy_io_slots.borrowed_tokens, 0)

    async def test_capacity_is_held_until_the_upstream_connection_has_closed(self) -> None:
        closing, finish = asyncio.Event(), asyncio.Event()

        class HeldClose(FakeAudioClient):
            async def send(self, *args, **kwargs):
                response = await super().send(*args, **kwargs)
                original = response.aclose

                async def close():
                    closing.set()
                    await finish.wait()
                    await original()

                response.aclose = close
                return response

        self.build(HeldClose(), max_concurrent_heavy_io=1)
        browser = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=self.app), base_url="https://module.example.test",
                                    cookies={SESSION_COOKIE: self.session_id})
        self.addAsyncCleanup(browser.aclose)
        first = asyncio.create_task(browser.get(AUDIO))
        try:
            await asyncio.wait_for(closing.wait(), 2)
            self.assertEqual((await browser.get(AUDIO)).status_code, 503, "a closing connection is still occupied")
        finally:
            finish.set()
            result = await first
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.app.state.heavy_io_slots.borrowed_tokens, 0)

    async def test_a_module_operation_and_file_share_the_upload_limit_and_leave_auth_available(self) -> None:
        fake = FakeAudioClient()
        fake.hold = asyncio.Event()
        self.build(fake, max_concurrent_heavy_io=2)
        browser = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=self.app), base_url="https://module.example.test",
                                    cookies={SESSION_COOKIE: self.session_id})
        self.addAsyncCleanup(browser.aclose)
        request = Request({"type": "http", "app": self.app, "headers": []})
        stream = None
        with heavy_io_slot(request) as admitted:
            self.assertTrue(admitted)
            stream = asyncio.create_task(browser.get(AUDIO))
            try:
                for _ in range(200):
                    if self.app.state.heavy_io_slots.borrowed_tokens == 2:
                        break
                    await asyncio.sleep(0.01)
                self.assertEqual(self.app.state.heavy_io_slots.borrowed_tokens, 2)
                minted = len(fake.signed_url_calls)
                rejected = await browser.get("/audio/flow-1/run-2/file-2")
                self.assertEqual(rejected.status_code, 503)
                self.assertEqual(len(fake.signed_url_calls), minted)
                taken = 0

                async def body():
                    nonlocal taken
                    taken += 1
                    yield b"not read"

                upload = await browser.post("/upload/flow-1", content=body(), headers={**ORIGIN, "Content-Type": "multipart/form-data; boundary=x", "Content-Length": "100"})
                self.assertEqual(upload.status_code, 503)
                self.assertEqual(taken, 0)
                self.assertEqual((await browser.get("/api/auth/status")).status_code, 200)
                with heavy_io_slot(request) as extra:
                    self.assertFalse(extra, "the module maps its own overload without opening an upstream")
            finally:
                fake.hold.set()
                await stream
        self.assertEqual(self.app.state.heavy_io_slots.borrowed_tokens, 0)
        with self.assertRaisesRegex(RuntimeError, "module failed"), heavy_io_slot(request) as admitted:
            self.assertTrue(admitted)
            raise RuntimeError("module failed")
        self.assertEqual(self.app.state.heavy_io_slots.borrowed_tokens, 0)


if __name__ == "__main__":
    unittest.main()
