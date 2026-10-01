import time
import unittest

import httpx
from fastapi import Depends, File, Request, Response, UploadFile
from fastapi.testclient import TestClient

from eneo_module_bff.app import create_app
from eneo_module_bff.auth import SESSION_COOKIE, ModuleSession, ModuleUser
from eneo_module_bff.deps import require_same_origin, require_session
from eneo_module_bff.settings import Settings
from eneo_module_bff.transport import (
    _rebase_signed_url,
    _requested_upload_timeout_seconds,
    _upload_timeout,
    forward_upload,
    stream_signed,
)

SIGNED = "https://eneo.example.test/api/v1/files/file-1/download/?token=abc"
ORIGIN = {"Origin": "https://module.example.test"}


def make_settings() -> Settings:
    return Settings(
        eneo_backend_url="https://eneo.example.test",
        eneo_public_url="https://eneo.example.test",
        module_public_url="https://module.example.test",
        module_key="speech-to-text",
        eneo_api_key="test-key",
        session_secret="x" * 48,
        cookie_secure=False,
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

    def build(self, http_client) -> None:
        self.app = create_app(make_settings(), http_client=http_client)
        self.uploads: list[UploadFile] = []

        @self.app.post(
            "/upload/{flow_id}",
            dependencies=[Depends(require_session), Depends(require_same_origin)],
        )
        async def upload(flow_id: str, request: Request, upload_file: UploadFile = File(...)) -> Response:
            self.uploads.append(upload_file)
            # Leave the stream at its end, and make reading it a failure: forward_upload must rewind it
            # and pass the stream on, not its bytes.
            await upload_file.read()

            async def read(*_: object) -> bytes:
                raise AssertionError("forward_upload must pass the upload stream")

            upload_file.read = read  # type: ignore[method-assign]
            return await forward_upload(request, f"flows/{flow_id}/files/", upload_file)

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

        self.client = TestClient(self.app)
        self.client.cookies.set(SESSION_COOKIE, self.app.state.module_auth.sessions.create(module_session()))

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
    def __init__(self) -> None:
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
            status_code = 200
            headers = {"content-type": "application/json"}

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
        self.assertIs(file_obj, self.uploads[0].file)
        self.assertEqual(client.body, b"audio", "rewound to the start")
        self.assertEqual(content_type, "audio/webm")
        self.assertEqual(client.headers["X-API-Key"], "test-key")
        self.assertEqual(
            client.headers["Authorization"],
            "Bearer module-user-token",
        )
        self.assertEqual(client.timeout.read, 120.0)

    def test_proxy_upload_maps_upstream_timeout_to_504(self) -> None:
        self.build(RaisingHttpClient(httpx.TimeoutException("stalled")))

        with self.assertLogs("eneo_proxy", level="ERROR"):
            response = self.upload_file()

        self.assertEqual(response.status_code, 504)

    def test_proxy_upload_maps_upstream_request_error_to_502(self) -> None:
        self.build(RaisingHttpClient(httpx.ConnectError("unreachable")))

        with self.assertLogs("eneo_proxy", level="ERROR"):
            response = self.upload_file()

        self.assertEqual(response.status_code, 502)

    def test_an_upload_path_that_leaves_its_route_is_refused_before_eneo_is_called(self) -> None:
        client = RaisingHttpClient(httpx.ConnectError("must not be called"))
        self.build(client)

        # %2E%2E decodes to a dot segment; a decoded "?" or "#" would move the rest of the path into a query.
        for flow_id in ("%2E%2E", "%2E", "x%3F", "x%23"):
            response = self.upload_file(flow_id)
            self.assertEqual(response.status_code, 403, flow_id)
            self.assertEqual(response.json(), {"detail": "Eneo resource is not exposed"})
        self.assertEqual(client.calls, 0)

    def test_a_control_character_or_a_backslash_in_an_upload_id_is_refused_before_eneo_is_called(self) -> None:
        client = RaisingHttpClient(httpx.ConnectError("must not be called"))
        self.build(client)

        for flow_id in ("a%00b", "a%0Db", "a%0Ab", "a%7Fb", "a%5Cb"):
            response = self.upload_file(flow_id)
            self.assertEqual(response.status_code, 403, flow_id)
        self.assertEqual(client.calls, 0)

    def test_an_upload_needs_a_session_and_the_modules_origin(self) -> None:
        client = RaisingHttpClient(httpx.ConnectError("must not be called"))
        self.build(client)

        cross_origin = self.upload_file(headers={"Origin": "https://attacker.example.test"})
        self.client.cookies.clear()
        anonymous = self.upload_file()

        self.assertEqual(cross_origin.status_code, 403)
        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(client.calls, 0)


class FakeSignedUrlResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code

    def json(self):
        if self.status_code != 200:
            return {"code": "file_unavailable"}
        return {"url": SIGNED, "expires_at": int(time.time()) + 900}


class FakeStreamResponse:
    def __init__(self, status_code: int, headers: dict[str, str], body: bytes) -> None:
        self.status_code = status_code
        self.headers = httpx.Headers(headers)
        self._body = body
        self.closed = False

    async def aiter_raw(self):
        yield self._body

    async def aread(self):
        return self._body

    async def aclose(self):
        self.closed = True


class FakeAudioClient:
    def __init__(self) -> None:
        self.signed_url_calls: list[dict[str, object]] = []
        self.stream_requests: list[httpx.Request] = []
        self.stream_responses: list[FakeStreamResponse] = []
        self.mint_status = 200
        self.stream_status = 200
        self.mint_error: Exception | None = None
        self.stream_error: Exception | None = None

    async def post(self, url, **kwargs):
        self.signed_url_calls.append({"url": url, **kwargs})
        if self.mint_error is not None:
            raise self.mint_error
        return FakeSignedUrlResponse(self.mint_status)

    def build_request(self, method, url, headers=None):
        return httpx.Request(method, url, headers=headers)

    async def send(self, request, stream=False):
        self.stream_requests.append(request)
        if self.stream_error is not None:
            raise self.stream_error
        response = self.respond(request)
        self.stream_responses.append(response)
        return response

    def respond(self, request) -> FakeStreamResponse:
        if self.stream_status >= 400:
            return FakeStreamResponse(
                self.stream_status,
                {"content-type": "application/json"},
                b'{"detail": "The link has expired."}',
            )
        if "range" in request.headers:
            return FakeStreamResponse(
                206,
                {
                    "content-type": "audio/webm",
                    "content-range": "bytes 0-3/10",
                    "content-length": "4",
                    "accept-ranges": "bytes",
                    "set-cookie": "leak=1",
                },
                b"abcd",
            )
        return FakeStreamResponse(
            200,
            {"content-type": "audio/webm", "content-length": "10"},
            b"0123456789",
        )


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
        self.assertEqual(len(self.app.state.signed_urls), 1)

        self.fake.stream_status = 403
        rejected = self.client.get(AUDIO)

        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(self.app.state.signed_urls, {})
        self.assertTrue(self.fake.stream_responses[-1].closed)

        self.fake.stream_status = 200
        again = self.client.get(AUDIO)

        self.assertEqual(again.status_code, 200)
        self.assertEqual(len(self.fake.signed_url_calls), 2)

    def test_each_session_has_its_own_signed_url(self) -> None:
        self.client.get(AUDIO)
        other = TestClient(self.app)
        other.cookies.set(SESSION_COOKIE, self.app.state.module_auth.sessions.create(module_session()))

        other.get(AUDIO)

        self.assertEqual(len(self.fake.signed_url_calls), 2)
        self.assertEqual(len(self.app.state.signed_urls), 2)

    def test_eneo_refusing_the_file_passes_through_without_a_stream(self) -> None:
        self.fake.mint_status = 410

        response = self.client.get(AUDIO)

        self.assertEqual(response.status_code, 410)
        self.assertEqual(self.fake.stream_requests, [])
        self.assertEqual(self.app.state.signed_urls, {})

    def test_eneo_not_answering_is_a_502_when_minting_and_when_streaming(self) -> None:
        self.fake.mint_error = httpx.ConnectError("unreachable")
        with self.assertLogs("eneo_proxy", level="ERROR"):
            minting = self.client.get(AUDIO)
        self.assertEqual((minting.status_code, minting.json()), (502, {"detail": "Eneo could not be reached."}))

        self.fake.mint_error = None
        self.fake.stream_error = httpx.ReadTimeout("stalled")
        with self.assertLogs("eneo_proxy", level="ERROR"):
            streaming = self.client.get(AUDIO)
        self.assertEqual(
            (streaming.status_code, streaming.json()),
            (502, {"error": "upstream_unreachable", "detail": "Eneo could not be reached."}),
        )


if __name__ == "__main__":
    unittest.main()
