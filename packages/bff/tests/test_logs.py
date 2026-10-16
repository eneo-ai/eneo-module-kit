"""No credential in the logs: a call to Eneo that goes wrong logs why, and never a token, the service key or a signed URL.

A validation error quotes the answer it refused, and httpx2's error for a header it cannot send quotes the header, so the
package logs the kind of an error, never its text. Every line any logger emits meanwhile is read, whatever its level.
"""

import asyncio
import contextlib
import logging
import time
import unittest
from collections.abc import AsyncIterator, Iterator
from urllib.parse import parse_qs, urlparse

import httpx2
from fastapi import APIRouter, Depends, Request, Response
from fastapi.testclient import TestClient

from eneo_module_bff.app import create_app
from eneo_module_bff.auth import SESSION_COOKIE, ModuleSession, ModuleUser
from eneo_module_bff.deps import require_same_origin, require_session
from eneo_module_bff.proxy import rule
from eneo_module_bff.settings import Settings
from eneo_module_bff.transport import forward_upload, stream_signed
from eneo_module_bff.upstream import make_client

from .test_auth import token_payload

# Short: a validation error quotes an input of up to 50 characters whole, a longer one by its first and last 25.
TOKEN = "tok-3f9a1c"
SERVICE_KEY = "test-key"
SIGNED = "https://eneo.example.test/api/v1/files/file-1/download/?token=signed-secret"
SECRETS = (TOKEN, SERVICE_KEY, "signed-secret")


@contextlib.contextmanager
def every_log_line() -> Iterator[list[str]]:
    """Every record any logger emits meanwhile, at any level, formatted with its traceback."""
    lines: list[str] = []

    class Keep(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(self.format(record))

    root, handler = logging.getLogger(), Keep(logging.DEBUG)
    level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        yield lines
    finally:
        root.removeHandler(handler)
        root.setLevel(level)


def unsendable(value: str) -> httpx2.LocalProtocolError:
    """What httpx2 raises for a header value it cannot send (a CR or LF in it): the value, quoted."""
    return httpx2.LocalProtocolError(f"Illegal header value b'{value}'")


def raising(error: Exception):
    def eneo(request: httpx2.Request) -> httpx2.Response:
        raise error
    return eneo


class CutOff(httpx2.AsyncByteStream):
    """An answer's body that breaks off, with the URL it came from in the error."""

    async def __aiter__(self) -> AsyncIterator[bytes]:
        raise httpx2.ReadError(f"cut off while reading {SIGNED}")
        yield b""


class NoCredentialInTheLogsTests(unittest.TestCase):
    def build(self, eneo) -> TestClient:
        """A module with a proxy rule, an upload route and a file route, whose Eneo answers with ``eneo``."""
        settings = Settings(
            eneo_backend_url="https://eneo.example.test", eneo_public_url="https://eneo.example.test",
            module_public_url="https://module.example.test", module_key="speech-to-text", eneo_api_key=SERVICE_KEY,
            session_secret="x" * 48, cookie_secure=False,
        )
        http = make_client(settings, transport=httpx2.MockTransport(eneo))
        self.addCleanup(lambda: asyncio.run(http.aclose()))
        router = APIRouter()

        @router.post("/api/upload", dependencies=[Depends(require_session), Depends(require_same_origin)])
        async def upload(request: Request) -> Response:
            return await forward_upload(request, "flows/flow-1/files/")

        @router.get("/api/file", dependencies=[Depends(require_session)])
        async def file(request: Request) -> Response:
            return await stream_signed(request, "file-1", mint_path="files/file-1/signed-url/", unavailable="No file.")

        self.app = create_app(settings, routers=[router], proxy_rules=[rule("GET", r"things/$")], http_client=http)
        return TestClient(self.app, follow_redirects=False)

    def signed_in(self, eneo, *, refresh_due: bool = False) -> TestClient:
        client = self.build(eneo)
        now = int(time.time())
        session = ModuleSession(
            access_token=TOKEN, expires_at=now + 100, refresh_at=now - 1 if refresh_due else now + 50,
            session_expires_at=now + 3600, module_key="speech-to-text", tenant_id="tenant-id",
            user=ModuleUser(id="user-id", email="user@example.test"),
        )
        client.cookies.set(SESSION_COOKIE, self.app.state.module_auth.sessions.create(session))
        return client

    def assert_says_why_and_nothing_secret(self, lines: list[str], *secrets: str) -> None:
        self.assertTrue(lines, "it says why")
        for secret in (*SECRETS, *secrets):
            self.assertNotIn(secret, "\n".join(lines))

    def test_a_login_that_goes_wrong(self) -> None:
        def exchange(answer):
            def eneo(request: httpx2.Request) -> httpx2.Response:
                if request.url.path == "/api/v1/module-auth/token/":
                    return httpx2.Response(200, json=token_payload(TOKEN))
                if isinstance(answer, Exception):
                    raise answer
                return answer
            return eneo

        cases = {
            "an exchange that cannot be sent": raising(unsendable(SERVICE_KEY)),
            "an exchange answer that is not a token": lambda _: httpx2.Response(200, json={"access_token": TOKEN}),
            "a session check that cannot be sent": exchange(unsendable(f"Bearer {TOKEN}")),
            "a session check answer that is not a session": exchange(httpx2.Response(200, json={"access_token": TOKEN})),
        }
        for case, eneo in cases.items():
            with self.subTest(case):
                client = self.build(eneo)
                state = parse_qs(urlparse(client.get("/api/auth/login").headers["location"]).query)["state"][0]
                with every_log_line() as lines:
                    location = client.get("/api/auth/callback", params={"ticket": "t-1", "state": state}).headers["location"]

                self.assertTrue(location.startswith("/?auth_error="), location)
                self.assert_says_why_and_nothing_secret(lines)

    def test_a_refresh_that_goes_wrong(self) -> None:
        renewed = "tok-renewed"
        cases = {
            "an answer that is not a token": lambda _: httpx2.Response(200, json={"access_token": renewed}),
            "a refresh that cannot be sent": raising(unsendable(f"Bearer {TOKEN}")),
            "an error nobody expected": raising(RuntimeError(f"unexpected, with {TOKEN} in it")),
        }
        for case, eneo in cases.items():
            with self.subTest(case):
                client = self.signed_in(eneo, refresh_due=True)
                with every_log_line() as lines:
                    client.get("/api/auth/status")

                self.assert_says_why_and_nothing_secret(lines, renewed)

    def test_a_proxied_call_that_goes_wrong(self) -> None:
        client = self.signed_in(raising(unsendable(f"Bearer {TOKEN}")))
        with every_log_line() as lines:
            response = client.get("/api/eneo/things/")

        self.assertEqual(response.status_code, 502)
        self.assert_says_why_and_nothing_secret(lines)

    def test_an_upload_that_goes_wrong(self) -> None:
        cases = {
            "an upload that cannot be sent": (raising(unsendable(f"Bearer {TOKEN}")), 502),
            "an upload that times out": (raising(httpx2.WriteTimeout(f"timed out sending Bearer {TOKEN}")), 504),
        }
        for case, (eneo, status) in cases.items():
            with self.subTest(case):
                client = self.signed_in(eneo)
                with every_log_line() as lines:
                    response = client.post(
                        "/api/upload", headers={"Origin": "https://module.example.test"},
                        files={"upload_file": ("a.bin", b"x", "application/octet-stream")},
                    )

                self.assertEqual(response.status_code, status)
                self.assert_says_why_and_nothing_secret(lines)

    def test_a_file_that_goes_wrong(self) -> None:
        def minted(answer):
            def eneo(request: httpx2.Request) -> httpx2.Response:
                if request.url.path == "/api/v1/files/file-1/signed-url/":
                    return httpx2.Response(200, json={"url": SIGNED})
                if isinstance(answer, Exception):
                    raise answer
                return answer
            return eneo

        cases = {
            "a signed URL that cannot be asked for": raising(unsendable(f"Bearer {TOKEN}")),
            "a file that cannot be reached": minted(httpx2.ConnectError(f"cannot connect for {SIGNED}")),
            "a refusal whose body breaks off": minted(httpx2.Response(500, stream=CutOff())),
        }
        for case, eneo in cases.items():
            with self.subTest(case):
                client = self.signed_in(eneo)
                with every_log_line() as lines:
                    response = client.get("/api/file")

                self.assertEqual(response.status_code, 502)
                self.assert_says_why_and_nothing_secret(lines)


if __name__ == "__main__":
    unittest.main()
