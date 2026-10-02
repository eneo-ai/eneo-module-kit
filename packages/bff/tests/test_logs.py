"""No log record carries a URL with a token in it, or any secret, however a call to Eneo ends.

A module app usually configures logging at INFO, and httpx2 logs every request's full URL at INFO: Eneo's signed file
URL carries its bearer token in the query string, and a proxied call carries the user's query. Each flow below runs
through the real app and a real httpx2 client whose transport answers from the test, with a distinct dummy sentinel for
every secret that is on the wire, and none may appear in any record the root logger sees (message, arguments,
traceback). The failures keep the sentence that diagnoses them.
"""

import logging
import time
import unittest
from datetime import datetime, timedelta, timezone

import httpx2
from fastapi import APIRouter, Depends, Request

from eneo_module_bff.auth import SESSION_COOKIE
from eneo_module_bff.deps import require_same_origin, require_session
from eneo_module_bff.proxy import rule
from eneo_module_bff.transport import forward_upload, stream_signed

from .fake_eneo import ORIGIN, Module, session

FILE_TOKEN = "SENTINEL-signed-file-token"
QUERY = "SENTINEL-search-terms"
TICKET = "SENTINEL-login-ticket"
ACCESS = "SENTINEL-module-access-token"
REFRESHED = "SENTINEL-refreshed-access-token"
SENTINELS = (FILE_TOKEN, QUERY, TICKET, ACCESS, REFRESHED)
SIGNED = f"http://eneo.example/api/v1/files/f1/download/?token={FILE_TOKEN}"

router = APIRouter()


@router.post("/upload/f1", dependencies=[Depends(require_session), Depends(require_same_origin)])
async def upload(request: Request):
    return await forward_upload(request, "flows/f1/files/")


@router.get("/files/f1", dependencies=[Depends(require_session)])
async def download(request: Request):
    return await stream_signed(request, "f1", mint_path="files/f1/signed-url/", unavailable="no file")


class Capture(logging.Handler):
    """Every record the root logger sees, as it would be written: message, arguments and traceback."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []
        self.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        # Not the test's own client calling the app (http://module.example.test/...): in production that is the browser.
        if record.name == "httpx2" and ORIGIN in record.getMessage():
            return
        self.lines.append(self.format(record))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


class Body(httpx2.AsyncByteStream):
    """An answer's body, read from the wire as it is used: httpx2.Response(content=...) arrives already read."""

    def __init__(self, content: bytes) -> None:
        self.content = content

    async def __aiter__(self):
        yield self.content


def streamed(status: int, content: bytes = b"", **headers: str) -> httpx2.Response:
    return httpx2.Response(status, headers=headers, stream=Body(content))


def refuse(error: Exception):
    def answer(request: httpx2.Request):
        raise error

    return answer


class Eneo(httpx2.AsyncBaseTransport):
    """Eneo: ``answer(request)`` is the current test's, and may raise a transport error."""

    def __init__(self) -> None:
        self.answer = lambda request: httpx2.Response(500)

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        return self.answer(request)


def token_payload(access_token: str, user_id: str = "u") -> dict[str, object]:
    return {
        "access_token": access_token, "token_type": "bearer", "expires_in": 900,
        "session_expires_at": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
        "module_key": "fake", "tenant_id": "t", "user": {"id": user_id, "email": "u@example.test"},
    }


class LogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # What a module's logging setup usually says; whatever ran before, it is INFO here.
        root = logging.getLogger()
        self.addCleanup(root.setLevel, root.level)
        root.setLevel(logging.INFO)
        self.capture = Capture()
        root.addHandler(self.capture)
        self.addCleanup(root.removeHandler, self.capture)
        self.eneo = Eneo()
        self.module = Module(self, transport=self.eneo, routers=(router,), proxy_rules=(rule("GET", r"things/$"),))

    def assert_clean(self, diagnosis: str | None = None) -> None:
        text = self.capture.text
        for sentinel in SENTINELS:
            self.assertNotIn(sentinel, text, f"{sentinel} was logged:\n{text}")
        self.assertNotIn("token=", text, text)
        if diagnosis is not None:
            self.assertIn(diagnosis, text, "the failure no longer says what happened")

    def browser(self, *, refresh_at: int | None = None) -> httpx2.AsyncClient:
        browser = self.module.browser(signed_in=False)
        due = session(ACCESS) if refresh_at is None else session(ACCESS).model_copy(update={"refresh_at": refresh_at})
        browser.cookies.set(SESSION_COOKIE, self.module.app.state.module_auth.sessions.create(due))
        return browser

    async def test_the_httpx2_loggers_are_held_at_warning_whatever_the_root_logger_says(self) -> None:
        for name in ("httpx2", "httpcore2"):
            self.assertGreaterEqual(logging.getLogger(name).getEffectiveLevel(), logging.WARNING, name)

    # ---- login and callback

    async def test_a_login_logs_no_secret_whether_it_succeeds_or_fails(self) -> None:
        def accepted(request: httpx2.Request):
            if request.url.path.endswith("/token/"):
                return httpx2.Response(200, json=token_payload(ACCESS))
            return httpx2.Response(200, json={k: v for k, v in token_payload(ACCESS).items() if k in ("module_key", "tenant_id", "user")})

        cases = {
            "succeeds": (accepted, "/", None),
            "is refused": (lambda request: httpx2.Response(401, json={"detail": f"bad {TICKET}"}), "exchange_failed", "Module ticket exchange failed with status 401"),
            "is unreachable": (refuse(httpx2.ConnectError("connection refused")), "exchange_unavailable", "Module ticket exchange could not reach Eneo"),
            "answers nonsense": (lambda request: httpx2.Response(200, json={"access_token": ACCESS, "token_type": "nonsense"}), "exchange_invalid", "Module ticket exchange returned an invalid response"),
        }
        for label, (answer, landing, diagnosis) in cases.items():
            with self.subTest(label):
                self.capture.lines.clear()
                self.eneo.answer = answer
                browser = self.module.browser(signed_in=False)
                state = httpx2.URL((await browser.get("/api/auth/login")).headers["location"]).params["state"]

                callback = await browser.get("/api/auth/callback", params={"ticket": TICKET, "state": state})

                self.assertIn(landing, callback.headers["location"])
                self.assert_clean(diagnosis)

    # ---- a signed file stream

    def file_answers(self, file_answer):
        def answer(request: httpx2.Request):
            if request.url.path.endswith("/signed-url/"):
                return httpx2.Response(200, json={"url": SIGNED, "expires_at": int(time.time()) + 900})
            return file_answer(request)

        return answer

    async def test_a_signed_file_stream_never_logs_the_url_with_its_token(self) -> None:
        self.eneo.answer = self.file_answers(lambda request: streamed(200, b"0123456789", **{"content-type": "audio/webm"}))

        response = await self.browser().get("/files/f1")

        self.assertEqual((response.status_code, response.content), (200, b"0123456789"))
        self.assert_clean()

    async def test_a_signed_file_stream_that_fails_logs_what_happened_and_no_token(self) -> None:
        cases = {
            "the file is gone": (lambda request: streamed(404, f'{{"detail": "no {FILE_TOKEN}"}}'.encode(), **{"content-type": "application/json"}), 404, None),
            "the file server fails": (lambda request: streamed(500, b"boom"), 500, None),
            "the file server is unreachable": (refuse(httpx2.ConnectError("connection refused")), 502, "File stream request failed: path=files/f1/signed-url/"),
            "the file is a redirect": (lambda request: streamed(307, location=f"http://elsewhere.example/?token={FILE_TOKEN}"), 502, "File stream was answered with a redirect: path=files/f1/signed-url/"),
        }
        for label, (file_answer, status, diagnosis) in cases.items():
            with self.subTest(label):
                self.capture.lines.clear()
                self.module.app.state.module_auth.sessions.clear()
                self.eneo.answer = self.file_answers(file_answer)

                response = await self.browser().get("/files/f1")

                self.assertEqual(response.status_code, status)
                self.assert_clean(diagnosis)

    # ---- a proxied call and an upload

    async def test_a_proxied_call_never_logs_the_users_query(self) -> None:
        self.eneo.answer = lambda request: httpx2.Response(200, json={"items": []})

        response = await self.browser().get(f"/api/eneo/things/?q={QUERY}")

        self.assertEqual(response.status_code, 200)
        self.assert_clean()

    async def test_an_upload_logs_no_secret_whether_it_succeeds_or_fails(self) -> None:
        cases = {
            "succeeds": (lambda request: httpx2.Response(200, json={"id": "f1"}), 200, None),
            "is refused": (lambda request: httpx2.Response(422, json={"detail": f"bad {ACCESS}"}), 422, None),
            "times out": (refuse(httpx2.ReadTimeout("read timed out")), 504, "Upload timed out: url=http://eneo.test/api/v1/flows/f1/files/"),
            "is unreachable": (refuse(httpx2.ConnectError("connection refused")), 502, "Upload failed: url=http://eneo.test/api/v1/flows/f1/files/"),
        }
        for label, (answer, status, diagnosis) in cases.items():
            with self.subTest(label):
                self.capture.lines.clear()
                self.eneo.answer = answer

                response = await self.browser().post("/upload/f1", files={"upload_file": ("a.webm", b"audio", "audio/webm")})

                self.assertEqual(response.status_code, status)
                self.assert_clean(diagnosis)

    # ---- a refresh

    async def test_a_refresh_logs_no_secret_whether_it_succeeds_or_fails(self) -> None:
        cases = {
            "succeeds": (lambda request: httpx2.Response(200, json=token_payload(REFRESHED, user_id=ACCESS)), True, None),
            "is refused": (lambda request: httpx2.Response(401, json={"detail": f"bad {ACCESS}"}), False, "Eneo refused the module token refresh with status 401"),
            "fails upstream": (lambda request: httpx2.Response(503, json={"detail": f"down {ACCESS}"}), True, "Module token refresh failed with status 503"),
            "is unreachable": (refuse(httpx2.ConnectError("connection refused")), True, "Module token refresh could not reach Eneo"),
            "answers nonsense": (lambda request: httpx2.Response(200, json={"access_token": REFRESHED, "token_type": "nonsense"}), False, "Module token refresh returned an invalid response"),
        }
        for label, (answer, still_signed_in, diagnosis) in cases.items():
            with self.subTest(label):
                self.capture.lines.clear()
                self.module.app.state.module_auth.sessions.clear()
                self.eneo.answer = answer

                status = await self.browser(refresh_at=int(time.time()) - 1).get("/api/auth/status")

                self.assertEqual(status.json()["authenticated"], still_signed_in)
                self.assert_clean(diagnosis)


if __name__ == "__main__":
    unittest.main()
