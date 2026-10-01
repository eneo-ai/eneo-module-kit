"""A redirect from Eneo on a call that carries a credential: a controlled answer, and a second server that hears nothing.

Two servers sit behind the module's real client: Eneo, which answers every call with a 307 to the second, and the second,
which records anything it receives. If the client followed the redirect, the service key or the module token would arrive there.
"""

import json
import time
import unittest

import httpx2
from fastapi import APIRouter, Depends, Request

from eneo_module_bff.auth import SESSION_COOKIE
from eneo_module_bff.deps import require_same_origin, require_session
from eneo_module_bff.proxy import rule
from eneo_module_bff.transport import forward_upload, stream_signed

from .fake_eneo import Answer, FakeEneo, Module, session

TOKEN = json.dumps({
    "access_token": "tok", "token_type": "bearer", "expires_in": 600, "session_expires_at": "2099-01-01T00:00:00Z",
    "module_key": "fake", "tenant_id": "t", "user": {"id": "u", "email": "u@example.test"},
}).encode()
ELSEWHERE = "http://other.test/collect"

router = APIRouter()


@router.post("/upload/f1", dependencies=[Depends(require_session), Depends(require_same_origin)])
async def upload(request: Request):
    return await forward_upload(request, "flows/f1/files/")


@router.get("/files/f1", dependencies=[Depends(require_session)])
async def download(request: Request):
    return await stream_signed(request, "f1", mint_path="files/f1/signed-url/", unavailable="no file")


def redirect() -> Answer:
    return Answer(status=307, body=b"", headers=[("location", ELSEWHERE)])


class Fork(httpx2.AsyncBaseTransport):
    """eneo.test goes to Eneo, other.test to the second server."""

    def __init__(self, eneo: FakeEneo, other: FakeEneo) -> None:
        self.apps = {"eneo.test": httpx2.ASGITransport(app=eneo), "other.test": httpx2.ASGITransport(app=other)}

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        return await self.apps[request.url.host].handle_async_request(request)


class RedirectTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.other = FakeEneo()

    def module(self, answer) -> tuple[FakeEneo, Module]:
        eneo = FakeEneo(answer)
        module = Module(self, transport=Fork(eneo, self.other), routers=(router,), proxy_rules=(rule("GET", r"things/$"),))
        return eneo, module

    def assert_nothing_followed(self, eneo: FakeEneo, module: Module) -> None:
        self.assertEqual(self.other.seen, [])
        self.assertTrue(eneo.seen, "the call was made, with its credential, to Eneo")
        self.assertIs(module.upstream.follow_redirects, False)

    async def login(self, module: Module):
        browser = module.browser(signed_in=False)
        state = httpx2.URL((await browser.get("/api/auth/login")).headers["location"]).params["state"]
        return browser, state

    async def test_the_ticket_exchange_that_is_redirected_ends_the_login_and_the_service_key_stays_with_eneo(self) -> None:
        eneo, module = self.module(lambda seen: redirect())
        browser, state = await self.login(module)

        response = await browser.get("/api/auth/callback", params={"ticket": "t", "state": state})

        self.assertEqual(response.headers["location"], "/?auth_error=exchange_failed")
        self.assertEqual(eneo.seen[0].headers["x-api-key"], "service-key")
        self.assert_nothing_followed(eneo, module)

    async def test_the_session_check_that_is_redirected_ends_the_login_and_the_module_token_stays_with_eneo(self) -> None:
        eneo, module = self.module(lambda seen: Answer(body=TOKEN) if seen.path.endswith("/token/") else redirect())
        browser, state = await self.login(module)

        response = await browser.get("/api/auth/callback", params={"ticket": "t", "state": state})

        self.assertEqual(response.headers["location"], "/?auth_error=validation_failed")
        self.assertEqual(eneo.seen[-1].headers["authorization"], "Bearer tok")
        self.assertNotIn(SESSION_COOKIE, response.headers.get("set-cookie", ""))
        self.assert_nothing_followed(eneo, module)

    async def test_a_token_refresh_that_is_redirected_is_refused_not_followed(self) -> None:
        eneo, module = self.module(lambda seen: redirect())
        now = int(time.time())
        due = session().model_copy(update={"refresh_at": now - 1})
        sessions = module.app.state.module_auth.sessions
        browser = module.browser()
        browser.cookies.set(SESSION_COOKIE, sessions.create(due))

        response = await browser.get("/api/auth/status")

        # Eneo refused the refresh (a 3xx is not an answer it can give): the login ends, nobody is signed in on a stale token.
        self.assertEqual(response.json(), {"authenticated": False, "user": None})
        self.assertEqual(eneo.seen[0].headers["authorization"], "Bearer token-of-u")
        self.assert_nothing_followed(eneo, module)

    async def test_a_signed_url_request_that_is_redirected_is_a_502_and_nothing_is_kept(self) -> None:
        eneo, module = self.module(lambda seen: redirect())
        browser = module.browser()

        response = await browser.get("/files/f1")

        self.assertEqual((response.status_code, response.json()["error"]), (502, "upstream_invalid"))
        self.assertIsNone(module.app.state.module_auth.sessions.signed_url(browser.cookies.get(SESSION_COOKIE), "files/f1/signed-url/"))
        self.assert_nothing_followed(eneo, module)

    async def test_an_upload_that_is_redirected_is_a_502_upstream_redirect(self) -> None:
        eneo, module = self.module(lambda seen: redirect())
        browser = module.browser()

        response = await browser.post("/upload/f1", files={"upload_file": ("a.bin", b"x", "application/octet-stream")})

        self.assertEqual((response.status_code, response.json()["error"]), (502, "upstream_redirect"))
        self.assert_nothing_followed(eneo, module)

    async def test_a_proxied_call_that_is_redirected_is_a_502_upstream_redirect(self) -> None:
        eneo, module = self.module(lambda seen: redirect())
        browser = module.browser()

        response = await browser.get("/api/eneo/things/")

        self.assertEqual((response.status_code, response.json()["error"]), (502, "upstream_redirect"))
        self.assertNotIn("location", response.headers)
        self.assert_nothing_followed(eneo, module)


if __name__ == "__main__":
    unittest.main()
