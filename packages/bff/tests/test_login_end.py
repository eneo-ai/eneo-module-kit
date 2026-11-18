"""The login's end, as Eneo says it: which of Eneo's refusals end the module's session, and only once Eneo confirms it.

Eneo answers a call made with a token it no longer takes (a changed password, "log out everywhere") with 401 and the code
authentication_error. So does a route of Eneo's that takes no module tokens, for a valid one, and so the session ends
only when Eneo's own session route refuses the same token. Every other refusal (the module's key, a 403, another 401
code) is Eneo's answer to pass on, and the session stays. The bodies below are Eneo's own, as its exception handlers
write them.
"""

import asyncio
import time
import unittest
from unittest.mock import patch

import httpx2
from fastapi import Depends, HTTPException, Request, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from eneo_module_bff import auth, raise_if_session_ended, require_session, upstream_auth_headers
from eneo_module_bff.app import create_app
from eneo_module_bff.auth import SESSION_COOKIE, ModuleAuth, ModuleSession, ModuleUser, SignedUrl, refuses_the_login
from eneo_module_bff.settings import Settings
from eneo_module_bff.upstream import SMALL_ANSWER, UnboundedAnswer

# A token Eneo no longer takes (revoked, expired, its user gone): the handler of AuthenticationException.
REVOKED = {"message": "Unauthenticated", "eneo_error_code": 9005, "code": "authentication_error", "request_id": "request-1"}
# The module's key refused: raise_api_key_http_error's body, with a copy of its detail.
KEY_REFUSED = {
    "code": "invalid_api_key",
    "message": "API key is invalid.",
    "context": {"auth_layer": "identity"},
    "request_id": "request-1",
    "eneo_error_code": 9005,
    "detail": {"code": "invalid_api_key", "message": "API key is invalid.", "context": {"auth_layer": "identity"}, "request_id": "request-1"},
}
NOT_REGISTERED = {"message": "API key is not registered for this module.", "eneo_error_code": 9001, "code": "forbidden", "context": {"auth_layer": "domain_policy"}}
INACTIVE = {"message": "Forbidden: you do not have permission to perform this action.", "eneo_error_code": 9019, "code": "user_inactive"}
# A refusal that asks for more of the same login (a step-up): it does not end it.
STEP_UP = {"message": "Step-up authentication is required.", "eneo_error_code": 9005, "code": "step_up_required"}

ENEO = "https://eneo.example.test"
SESSION_ROUTE = f"{ENEO}/api/v1/module-auth/eneo-module/session/"
SESSION_ROUTE_ACCEPTS = httpx2.Response(
    200, json={"module_key": "eneo-module", "tenant_id": "tenant-id", "user": {"id": "user-id", "email": "user@example.test"}}
)
ORIGIN = "https://module.example.test"


def settings() -> Settings:
    return Settings(
        eneo_backend_url=ENEO,
        eneo_public_url=ENEO,
        module_public_url=ORIGIN,
        module_key="eneo-module",
        eneo_api_key="service-key",
        session_secret="x" * 48,
        cookie_secure=False,
    )


def a_session(token: str = "module-user-token") -> ModuleSession:
    """A session whose token is not due for a refresh: nothing but a refusal can end it here."""
    now = int(time.time())
    return ModuleSession(
        access_token=token,
        expires_at=now + 600,
        refresh_at=now + 300,
        session_expires_at=now + 3600,
        module_key="eneo-module",
        tenant_id="tenant-id",
        user=ModuleUser(id="user-id", email="user@example.test"),
    )


class SessionRoute:
    """Eneo's session route as the module's client sees it: every check gets ``answer`` (a response, an exception to
    raise, or an async function that answers), and is counted."""

    def __init__(self, answer=SESSION_ROUTE_ACCEPTS) -> None:
        self.answer = answer
        self.calls: list[dict[str, object]] = []

    async def get(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if isinstance(self.answer, BaseException):
            raise self.answer
        if callable(self.answer):
            return await self.answer()
        return self.answer


class RefusalTests(unittest.TestCase):
    def test_only_a_401_with_the_code_authentication_error_at_the_top_may_end_the_login(self) -> None:
        cases = {
            "a token Eneo no longer takes": (httpx2.Response(401, json=REVOKED), True),
            "the same without a request id": (httpx2.Response(401, json={k: v for k, v in REVOKED.items() if k != "request_id"}), True),
            "the module's key refused": (httpx2.Response(401, json=KEY_REFUSED), False),
            "the key not registered for the module": (httpx2.Response(403, json=NOT_REGISTERED), False),
            "the user inactive": (httpx2.Response(403, json=INACTIVE), False),
            "the code on a 403": (httpx2.Response(403, json=REVOKED), False),
            "the code on a 200": (httpx2.Response(200, json=REVOKED), False),
            "another 401 code (a step-up)": (httpx2.Response(401, json=STEP_UP), False),
            "an unknown 401 code": (httpx2.Response(401, json={"code": "something_new", "message": "?"}), False),
            "a 401 without JSON": (httpx2.Response(401, text="<html>Unauthorized</html>"), False),
            "a 401 without a body": (httpx2.Response(401), False),
            "a 401 whose JSON has no code": (httpx2.Response(401, json={"detail": "Not authenticated"}), False),
            "the code only inside detail": (httpx2.Response(401, json={"detail": {"code": "authentication_error"}}), False),
            "a code that is not a string": (httpx2.Response(401, json={"code": ["authentication_error"]}), False),
            "a JSON list": (httpx2.Response(401, json=[REVOKED]), False),
            "bytes that are not UTF-8": (httpx2.Response(401, content=b"\xff\xfe"), False),
        }
        for case, (answer, ends) in cases.items():
            with self.subTest(case):
                self.assertIs(refuses_the_login(answer), ends)


class LoginEndCase(unittest.IsolatedAsyncioTestCase):
    """A ModuleAuth of its own, in front of a fake session route, and requests admitted the way the routes admit them."""

    def setUp(self) -> None:
        self.route = SessionRoute()
        self.auth = ModuleAuth(settings=settings(), http_client=self.route)
        self.session_id = self.auth.sessions.create(a_session())

    async def admitted(self, session_id: str | None = None) -> Request:
        request = Request({"type": "http", "method": "GET", "path": "/api/eneo/things/", "headers": []})
        await self.auth.require_session(request, session_id or self.session_id)
        return request

    def renew(self, token: str) -> None:
        """The refresh: a new token under the same session id."""
        self.auth.sessions.replace(self.session_id, a_session(token))

    def held_token(self) -> str | None:
        session = self.auth.sessions.get(self.session_id)
        return session.access_token if session else None


class ConfirmationTests(LoginEndCase):
    async def test_a_refusal_the_session_route_confirms_ends_the_session_and_its_signed_urls(self) -> None:
        self.route.answer = httpx2.Response(401, json=REVOKED)
        self.auth.sessions.remember_signed_url(self.session_id, "files/f1/signed-url/", SignedUrl("https://eneo/f1?sig", time.time() + 600))
        request = await self.admitted()

        ended = await self.auth.login_refused(request, httpx2.Response(401, json=REVOKED))

        self.assertTrue(ended)
        self.assertIsNone(self.auth.sessions.get(self.session_id))
        self.assertIsNone(self.auth.sessions.signed_url(self.session_id, "files/f1/signed-url/"), "a bearer URL to a file ends with its session")
        self.assertEqual(len(self.route.calls), 1)
        check = self.route.calls[0]
        self.assertEqual(check["url"], SESSION_ROUTE)
        self.assertEqual(check["headers"], {"X-API-Key": "service-key", "Authorization": "Bearer module-user-token"}, "the token that was refused")
        self.assertEqual(check["extensions"], SMALL_ANSWER)

    async def test_a_token_the_session_route_accepts_keeps_the_session(self) -> None:
        # A route of Eneo's that takes no module tokens refuses a valid one: a new login would not change that.
        request = await self.admitted()

        ended = await self.auth.login_refused(request, httpx2.Response(401, json=REVOKED))

        self.assertFalse(ended)
        self.assertEqual(self.held_token(), "module-user-token")
        self.assertEqual(len(self.route.calls), 1)
        # And each refusal like it is checked once, never in a loop.
        await self.auth.login_refused(request, httpx2.Response(401, json=REVOKED))
        self.assertEqual(len(self.route.calls), 2)

    async def test_no_confirmation_keeps_the_session(self) -> None:
        async def never():
            await asyncio.Event().wait()

        answers = {
            "another 401 code": httpx2.Response(401, json=KEY_REFUSED),
            "a 401 without the code": httpx2.Response(401, json={"detail": "no"}),
            "a 403": httpx2.Response(403, json=NOT_REGISTERED),
            "a 404": httpx2.Response(404, json={"code": "not_found", "message": "Not found"}),
            "too many requests": httpx2.Response(429, json={"code": "rate_limit_exceeded"}),
            "Eneo failing": httpx2.Response(503),
            "a 200 for someone else": httpx2.Response(200, json={"module_key": "eneo-module", "tenant_id": "t", "user": {"id": "other", "email": "o@x"}}),
            "a 200 that is not JSON": httpx2.Response(200, text="ok"),
            "unreachable": httpx2.ConnectError("unreachable"),
            "a read timeout": httpx2.ReadTimeout("slow"),
            "an answer past its bound": UnboundedAnswer("too long", request=httpx2.Request("GET", SESSION_ROUTE)),
            "no answer before the deadline": never,
        }
        for case, answer in answers.items():
            with self.subTest(case):
                self.route.answer, self.route.calls = answer, []
                request = await self.admitted()

                with patch.object(auth, "SESSION_CHECK_SECONDS", 0.05):
                    ended = await asyncio.wait_for(self.auth.login_refused(request, httpx2.Response(401, json=REVOKED)), 1)

                self.assertFalse(ended)
                self.assertEqual(self.held_token(), "module-user-token")
                self.assertEqual(len(self.route.calls), 1, "one check, not another")

    async def test_the_deadline_covers_the_whole_check_and_the_client_is_bounded_too(self) -> None:
        request = await self.admitted()

        await self.auth.login_refused(request, httpx2.Response(401, json=REVOKED))

        self.assertEqual(self.route.calls[0]["timeout"], httpx2.Timeout(auth.SESSION_CHECK_SECONDS))
        self.assertEqual(auth.SESSION_CHECK_SECONDS, 10.0)

    async def test_a_refusal_that_cannot_end_the_login_asks_nothing(self) -> None:
        request = await self.admitted()
        for answer in (
            httpx2.Response(401, json=KEY_REFUSED),
            httpx2.Response(403, json=INACTIVE),
            httpx2.Response(401, json=STEP_UP),
            httpx2.Response(401, json={"detail": "no code"}),
            httpx2.Response(401, content=b"\xff\xfe"),
            httpx2.Response(200, json={"items": []}),
        ):
            with self.subTest(status=answer.status_code, body=answer.content):
                self.assertFalse(await self.auth.login_refused(request, answer))
        self.assertEqual(self.route.calls, [])
        self.assertEqual(self.held_token(), "module-user-token")

    async def test_a_request_cancelled_during_the_check_leaves_no_work_behind_and_the_session_stays(self) -> None:
        asked = asyncio.Event()

        async def never():
            asked.set()
            await asyncio.Event().wait()

        self.route.answer = never
        request = await self.admitted()
        before = asyncio.all_tasks()
        check = asyncio.create_task(self.auth.login_refused(request, httpx2.Response(401, json=REVOKED)))
        await asyncio.wait_for(asked.wait(), 1)

        check.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await check

        self.assertEqual(asyncio.all_tasks() - before, set(), "the check ran in the request, and went with it")
        self.assertEqual(self.held_token(), "module-user-token")


class LateAndConcurrentRefusalTests(LoginEndCase):
    async def test_a_new_login_while_an_old_call_waits_keeps_the_new_session(self) -> None:
        old = await self.admitted()
        # The callback of a new login deletes the session the browser had and makes another.
        self.auth.sessions.delete(self.session_id)
        new_id = self.auth.sessions.create(a_session("new-login-token"))

        ended = await self.auth.login_refused(old, httpx2.Response(401, json=REVOKED))

        self.assertTrue(ended, "the old call gets the session answer: its session is gone, as require_session would say")
        self.assertEqual(self.auth.sessions.get(new_id).access_token, "new-login-token")
        self.assertEqual(self.route.calls, [], "nothing to confirm for a session that is gone")

    async def test_a_renewal_while_an_old_call_waits_keeps_the_session_and_says_nothing(self) -> None:
        old = await self.admitted()
        self.renew("renewed-token")

        ended = await self.auth.login_refused(old, httpx2.Response(401, json=REVOKED))

        self.assertFalse(ended, "Eneo's answer goes on: the session is signed in with a newer token")
        self.assertEqual(self.held_token(), "renewed-token")
        self.assertEqual(self.route.calls, [])

    async def test_a_renewal_while_the_check_waits_keeps_the_session_and_says_nothing(self) -> None:
        asked, answer = asyncio.Event(), asyncio.Event()

        async def confirms():
            asked.set()
            await answer.wait()
            return httpx2.Response(401, json=REVOKED)

        self.route.answer = confirms
        request = await self.admitted()
        refusal = asyncio.create_task(self.auth.login_refused(request, httpx2.Response(401, json=REVOKED)))
        await asyncio.wait_for(asked.wait(), 1)
        self.renew("renewed-token")
        answer.set()

        self.assertFalse(await refusal, "the old token's end is not the renewed session's")
        self.assertEqual(self.held_token(), "renewed-token")
        self.assertEqual(len(self.route.calls), 1)

    async def test_two_refusals_of_the_same_token_both_end_it_and_each_asks_once(self) -> None:
        # A page asks for two things at once: both come back refused.
        asked, answer = asyncio.Event(), asyncio.Event()

        async def confirms():
            if len(self.route.calls) == 2:
                asked.set()
            await answer.wait()
            return httpx2.Response(401, json=REVOKED)

        self.route.answer = confirms
        first, second = await self.admitted(), await self.admitted()
        refusals = asyncio.gather(
            self.auth.login_refused(first, httpx2.Response(401, json=REVOKED)),
            self.auth.login_refused(second, httpx2.Response(401, json=REVOKED)),
        )
        await asyncio.wait_for(asked.wait(), 1)
        answer.set()

        self.assertEqual(await refusals, [True, True], "both get the session answer")
        self.assertIsNone(self.auth.sessions.get(self.session_id))
        self.assertEqual(len(self.route.calls), 2, "at most one check per refusal")

    async def test_a_refusal_whose_own_check_confirms_nothing_after_another_ended_the_session_gets_the_answer(self) -> None:
        # Two refusals of the same token at once: the first check confirms and ends the session; the second check's
        # own answer confirms nothing, but the session it was about is gone all the same.
        for case in ("Eneo failing", "no answer before the deadline"):
            with self.subTest(case):
                self.session_id, self.route.calls = self.auth.sessions.create(a_session()), []
                both_asked, first_ended = asyncio.Event(), asyncio.Event()

                async def answers():
                    if len(self.route.calls) == 1:
                        await both_asked.wait()
                        return httpx2.Response(401, json=REVOKED)
                    both_asked.set()
                    await first_ended.wait()
                    if case == "Eneo failing":
                        return httpx2.Response(503)
                    await asyncio.Event().wait()

                self.route.answer = answers
                first, second = await self.admitted(), await self.admitted()
                with patch.object(auth, "SESSION_CHECK_SECONDS", 0.2):
                    one = asyncio.create_task(self.auth.login_refused(first, httpx2.Response(401, json=REVOKED)))
                    two = asyncio.create_task(self.auth.login_refused(second, httpx2.Response(401, json=REVOKED)))
                    self.assertTrue(await asyncio.wait_for(one, 1))
                    first_ended.set()
                    self.assertTrue(await asyncio.wait_for(two, 1), "the second gets the session answer too")

                self.assertIsNone(self.auth.sessions.get(self.session_id))
                self.assertEqual(len(self.route.calls), 2, "at most one check per refusal")

    async def test_a_refusal_after_the_session_ended_gets_the_answer_without_a_check(self) -> None:
        self.route.answer = httpx2.Response(401, json=REVOKED)
        first, second = await self.admitted(), await self.admitted()
        self.assertTrue(await self.auth.login_refused(first, httpx2.Response(401, json=REVOKED)))

        self.assertTrue(await self.auth.login_refused(second, httpx2.Response(401, json=REVOKED)))
        self.assertEqual(len(self.route.calls), 1)


class StoreTests(unittest.TestCase):
    def test_delete_if_token_deletes_only_the_session_that_still_holds_the_token(self) -> None:
        store = auth.ModuleSessionStore()
        session_id = store.create(a_session("old"))
        store.remember_signed_url(session_id, "files/f1/signed-url/", SignedUrl("https://eneo/f1?sig", time.time() + 600))
        store.replace(session_id, a_session("new"))

        self.assertFalse(store.delete_if_token(session_id, "old"), "renewed meanwhile: it stays")
        self.assertEqual(store.get(session_id).access_token, "new")
        self.assertTrue(store.delete_if_token(session_id, "new"))
        self.assertIsNone(store.get(session_id))
        self.assertIsNone(store.signed_url(session_id, "files/f1/signed-url/"))
        self.assertTrue(store.delete_if_token(session_id, "new"), "gone already: gone")


class _Arriving(httpx2.AsyncByteStream):
    """A body that arrives as a real one does: nothing of it is read until someone reads it."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    async def __aiter__(self):
        yield self._body


def eneo_refusing(resource_answer: httpx2.Response, session_answer: httpx2.Response = SESSION_ROUTE_ACCEPTS):
    """Eneo behind a mock transport: the session route answers ``session_answer``, every other call ``resource_answer``.
    The calls to the session route are counted in the returned list."""
    checks: list[httpx2.Request] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        if str(request.url) == SESSION_ROUTE:
            checks.append(request)
            return httpx2.Response(session_answer.status_code, stream=_Arriving(session_answer.content), headers=session_answer.headers)
        return httpx2.Response(resource_answer.status_code, stream=_Arriving(resource_answer.content), headers=resource_answer.headers)

    return httpx2.AsyncClient(transport=httpx2.MockTransport(answer)), checks


class PublicNameTests(unittest.TestCase):
    """``raise_if_session_ended``: what a module's own route calls with Eneo's answer to its own call."""

    def module(self, resource_answer: httpx2.Response, session_answer: httpx2.Response = SESSION_ROUTE_ACCEPTS, *, stream: bool = False):
        client, self.checks = eneo_refusing(resource_answer, session_answer)
        app = create_app(settings(), http_client=client)

        @app.get("/api/own", dependencies=[Depends(require_session)])
        async def own(request: Request) -> dict[str, int]:
            http = request.app.state.http
            if stream:
                answer = await http.send(http.build_request("GET", f"{ENEO}/api/v1/things/", headers=upstream_auth_headers(request)), stream=True)
            else:
                answer = await http.get(f"{ENEO}/api/v1/things/", headers=upstream_auth_headers(request))
            try:
                await raise_if_session_ended(request, answer)
            finally:
                await answer.aclose()
            return {"eneo": answer.status_code}

        @app.websocket("/api/socket")
        async def socket(websocket: WebSocket, _: ModuleSession = Depends(require_session)) -> None:
            if websocket.query_params.get("accept") == "first":
                await websocket.accept()
            answer = await websocket.app.state.http.get(f"{ENEO}/api/v1/things/", headers=upstream_auth_headers(websocket))
            await raise_if_session_ended(websocket, answer)
            if websocket.query_params.get("accept") != "first":
                await websocket.accept()
            await websocket.send_json({"eneo": answer.status_code})
            await websocket.close()

        self.app = app
        self.session_id = app.state.module_auth.sessions.create(a_session())
        browser = TestClient(app, base_url=ORIGIN)
        browser.cookies.set(SESSION_COOKIE, self.session_id)
        return browser

    def test_a_confirmed_end_is_the_kits_answer_for_an_ended_session(self) -> None:
        browser = self.module(httpx2.Response(401, json=REVOKED), httpx2.Response(401, json=REVOKED))

        response = browser.get("/api/own")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers.get("x-auth-required"), "session")
        self.assertEqual(response.json(), {"detail": "Not authenticated"}, "the kit's own answer, never Eneo's")
        self.assertIsNone(self.app.state.module_auth.sessions.get(self.session_id))
        self.assertEqual(len(self.checks), 1)
        self.assertEqual(self.checks[0].headers["Authorization"], "Bearer module-user-token")

    def test_any_other_answer_returns_and_the_route_answers_as_before(self) -> None:
        for answer, checks in (
            (httpx2.Response(200, json={"items": []}), 0),
            (httpx2.Response(401, json=KEY_REFUSED), 0),
            (httpx2.Response(403, json=INACTIVE), 0),
            (httpx2.Response(401, json=REVOKED), 1),  # the session route accepts the token
        ):
            with self.subTest(status=answer.status_code, body=answer.content):
                browser = self.module(answer)

                self.assertEqual(browser.get("/api/own").json(), {"eneo": answer.status_code})
                self.assertIsNotNone(self.app.state.module_auth.sessions.get(self.session_id))
                self.assertEqual(len(self.checks), checks)

    def test_an_answer_whose_body_was_not_read_fails_loudly_whatever_its_status(self) -> None:
        # A streamed call: the body is not read, so the rule cannot read it. The author is told what to do, on the first
        # call, not only on the rare 401.
        for answer in (httpx2.Response(200, json={"items": []}), httpx2.Response(401, json=REVOKED)):
            with self.subTest(status=answer.status_code):
                browser = self.module(answer, httpx2.Response(401, json=REVOKED), stream=True)

                with self.assertRaisesRegex(RuntimeError, r"raise_if_session_ended needs Eneo's answer read.*aread\(\)"):
                    browser.get("/api/own")
                self.assertIsNotNone(self.app.state.module_auth.sessions.get(self.session_id))
                self.assertEqual(self.checks, [])

    def test_a_socket_is_closed_with_1008_at_the_handshake_and_once_accepted(self) -> None:
        for when in ("handshake", "first"):
            with self.subTest(when):
                browser = self.module(httpx2.Response(401, json=REVOKED), httpx2.Response(401, json=REVOKED))

                with self.assertRaises(WebSocketDisconnect) as closed:
                    with browser.websocket_connect(f"/api/socket?accept={when}", headers={"Origin": ORIGIN}) as socket:
                        socket.receive_json()

                self.assertEqual((closed.exception.code, closed.exception.reason), (1008, "Not authenticated"))
                self.assertIsNone(self.app.state.module_auth.sessions.get(self.session_id))

    def test_the_kits_answer_is_the_one_require_session_gives(self) -> None:
        answer = auth.session_ended()

        self.assertIsInstance(answer, HTTPException)
        self.assertEqual((answer.status_code, answer.detail, answer.headers), (401, "Not authenticated", {"X-Auth-Required": "session"}))
        browser = self.module(httpx2.Response(200))
        browser.cookies.clear()
        refused = browser.get("/api/own")
        self.assertEqual((refused.status_code, refused.json(), refused.headers.get("x-auth-required")), (401, {"detail": "Not authenticated"}, "session"))


if __name__ == "__main__":
    unittest.main()
