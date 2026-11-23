import asyncio
import itertools
import os
import re
import secrets
import time
import timeit
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import httpx2
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from itsdangerous import URLSafeTimedSerializer

from eneo_module_bff.app import create_app
from eneo_module_bff.auth import (
    ModuleAuth,
    ModuleSession,
    ModuleSessionStore,
    MAX_HOME_PATH_BYTES,
    MAX_STATE_COOKIE_BYTES,
    ModuleUser,
    PendingLogin,
    SESSION_COOKIE,
    SignedUrl,
    STATE_COOKIE,
    module_path,
    state_cookie_name,
    with_query,
)
from eneo_module_bff.deps import require_session, upstream_auth_headers
from eneo_module_bff.settings import Settings

from .test_login_redirect import VECTORS

# Eneo's session ceiling in these tests; shorter than the module's 8-hour default.
ENEO_SESSION_SECONDS = 4 * 60 * 60


def build_auth(http_client) -> tuple[FastAPI, ModuleAuth]:
    """The app under test: create_app, plus one session-protected route that calls Eneo."""
    settings = Settings(
        eneo_backend_url="https://eneo.example.test",
        eneo_public_url="https://eneo.example.test",
        module_public_url="https://module.example.test",
        module_key="speech-to-text",
        eneo_api_key="test-key",
        session_secret="x" * 48,
        cookie_secure=False,
        home_path="/flows",
    )
    app = create_app(settings, http_client=http_client)

    @app.get("/resource", dependencies=[Depends(require_session)])
    async def resource(request: Request) -> dict[str, bool]:
        await request.app.state.http.request(
            method="GET",
            url="https://eneo.example.test/api/v1/flows/",
            headers=upstream_auth_headers(request),
        )
        return {"ok": True}

    return app, app.state.module_auth


def token_payload(
    access_token: str = "module-user-token",
    *,
    expires_in: int = 900,
    user_id: str = "user-id",
    naive: bool = False,
) -> dict[str, object]:
    """Eneo's ModuleTokenResponse, as the ticket exchange and refresh return it."""
    ceiling = datetime.fromtimestamp(time.time() + ENEO_SESSION_SECONDS, tz=timezone.utc)
    if naive:  # the same moment, written without a time zone
        ceiling = ceiling.replace(tzinfo=None)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "session_expires_at": ceiling.isoformat(),
        "module_key": "speech-to-text",
        "tenant_id": "tenant-id",
        "user": {
            "id": user_id,
            "email": "user@example.test",
            "username": "Test User",
        },
    }


def pending_logins(cookies) -> dict[str, str]:
    """The login states in a cookie jar or a response's cookies: one per sign-in that has not returned yet."""
    return {name: value for name, value in dict(cookies).items() if name.startswith(f"{STATE_COOKIE}_")}


def cookie_header(cookies: dict[str, str]) -> dict[str, str]:
    return {"Cookie": "; ".join(f"{name}={value}" for name, value in cookies.items())}


class FakeResponse:
    def __init__(self, status_code: int = 200, *, user_id: str = "user-id", naive: bool = False) -> None:
        self.status_code = status_code
        self.user_id = user_id
        self.naive = naive

    def json(self):
        return token_payload(user_id=self.user_id, naive=self.naive)


class FakeExchangeClient:
    def __init__(self, response: FakeResponse | None = None) -> None:
        self.response = response or FakeResponse()
        self.validation_response = FakeResponse()
        self.calls: list[dict[str, object]] = []

    async def post(self, url: str, **kwargs):
        self.calls.append({"method": "POST", "url": url, **kwargs})
        return self.response

    async def get(self, url: str, **kwargs):
        self.calls.append({"method": "GET", "url": url, **kwargs})
        return self.validation_response


class ModuleAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.exchange_client = FakeExchangeClient()
        app, self.auth = build_auth(self.exchange_client)
        self.client = TestClient(app, follow_redirects=False)

    def start_login(self) -> tuple[str, str]:
        response = self.client.get("/api/auth/login")

        self.assertEqual(response.status_code, 303)
        location = response.headers["location"]
        query = parse_qs(urlparse(location).query)
        self.assertEqual(query["module_key"], ["speech-to-text"])
        self.assertEqual(
            query["redirect_uri"],
            ["https://module.example.test/api/auth/callback"],
        )
        state = query["state"][0]
        self.assertEqual(list(pending_logins(response.cookies)), [state_cookie_name(state)])
        self.assertIn("Path=/api/auth;", response.headers["set-cookie"])
        return state, location

    def test_login_redirect_binds_state_to_callback_cookie(self) -> None:
        state, location = self.start_login()

        self.assertIn(f"state={state}", location)
        self.assertEqual(self.exchange_client.calls, [])

    def test_callback_exchanges_ticket_and_establishes_module_session(self) -> None:
        state, _ = self.start_login()

        callback = self.client.get(
            "/api/auth/callback",
            params={"ticket": "one-time-ticket", "state": state},
        )

        self.assertEqual(callback.status_code, 303)
        self.assertEqual(callback.headers["location"], "/flows")
        self.assertEqual(callback.headers["referrer-policy"], "no-referrer")
        self.assertIn("eneo_module_session", callback.cookies)
        self.assertNotIn(
            "module-user-token",
            callback.cookies[SESSION_COOKIE],
        )
        self.assertEqual(len(self.exchange_client.calls), 2)
        exchange = self.exchange_client.calls[0]
        self.assertEqual(
            exchange["url"],
            "https://eneo.example.test/api/v1/module-auth/token/",
        )
        self.assertEqual(exchange["headers"], {"X-API-Key": "test-key"})
        self.assertEqual(exchange["json"], {"ticket": "one-time-ticket"})
        validation = self.exchange_client.calls[1]
        self.assertEqual(validation["method"], "GET")
        self.assertEqual(
            validation["url"],
            "https://eneo.example.test/api/v1/module-auth/speech-to-text/session/",
        )
        self.assertEqual(
            validation["headers"],
            {
                "X-API-Key": "test-key",
                "Authorization": "Bearer module-user-token",
            },
        )

        status = self.client.get("/api/auth/status")
        self.assertEqual(status.headers["cache-control"], "no-store")
        body = status.json()
        # The page checks again once the 900-second token is half used.
        self.assertTrue(0 < body.pop("refresh_in") <= 450)
        self.assertTrue(0 < body.pop("session_ends_in") <= ENEO_SESSION_SECONDS)
        self.assertEqual(
            body,
            {
                "authenticated": True,
                "user": {
                    "id": "user-id",
                    "email": "user@example.test",
                    "username": "Test User",
                },
            },
        )

    def test_callback_session_outlives_the_module_token(self) -> None:
        state, _ = self.start_login()
        before = int(time.time())

        callback = self.client.get(
            "/api/auth/callback",
            params={"ticket": "one-time-ticket", "state": state},
        )

        after = int(time.time())
        session_cookie = next(
            header
            for header in callback.headers.get_list("set-cookie")
            if header.startswith(f"{SESSION_COOKIE}=")
        )
        max_age = int(re.search(r"Max-Age=(\d+)", session_cookie).group(1))
        # Eneo's 4-hour ceiling caps the module's 8-hour default, not the
        # 15-minute token: refresh keeps the session going until then.
        self.assertTrue(
            ENEO_SESSION_SECONDS - (after - before) - 1
            <= max_age
            <= ENEO_SESSION_SECONDS
        )
        session = self.auth.sessions.get(callback.cookies[SESSION_COOKIE])
        self.assertTrue(before + 900 <= session.expires_at <= after + 900)
        self.assertTrue(before + 450 <= session.refresh_at <= after + 450)

    def test_callback_rejects_mismatched_state_without_exchange(self) -> None:
        self.start_login()

        callback = self.client.get(
            "/api/auth/callback",
            params={"ticket": "one-time-ticket", "state": "wrong-state"},
        )

        self.assertEqual(callback.status_code, 303)
        self.assertEqual(callback.headers["location"], "/?auth_error=invalid_state")
        self.assertEqual(self.exchange_client.calls, [])

    def test_a_sign_in_that_takes_six_minutes_at_eneo_completes(self) -> None:
        # Signed out of Eneo, a person first signs in there; that alone may take longer than five minutes.
        state, _ = self.start_login()

        with patch("time.time", return_value=time.time() + 6 * 60):
            callback = self.client.get("/api/auth/callback", params={"ticket": "one-time-ticket", "state": state})

        self.assertEqual(callback.headers["location"], "/flows")
        self.assertIn(SESSION_COOKIE, callback.cookies)

    def test_a_sign_in_past_the_login_timeout_is_invalid_state_and_exchanges_nothing(self) -> None:
        # LOGIN_TIMEOUT_MINUTES sets the window; 10 minutes here, so the default is not what the test relies on.
        with patch.object(self.auth.settings, "login_timeout_seconds", 10 * 60):
            response = self.client.get("/api/auth/login")
            state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
            self.assertIn(f"Max-Age={10 * 60}", response.headers["set-cookie"])
            # A browser that kept the cookie past its Max-Age anyway: the signed age is checked on its own.
            waiting = pending_logins(response.cookies)
            self.client.cookies.clear()

            with patch("time.time", return_value=time.time() + 10 * 60 + 5):
                callback = self.client.get(
                    "/api/auth/callback",
                    params={"ticket": "one-time-ticket", "state": state},
                    headers=cookie_header(waiting),
                )

        self.assertEqual(callback.headers["location"], "/?auth_error=invalid_state")
        self.assertNotIn(SESSION_COOKIE, callback.cookies)
        self.assertEqual(self.exchange_client.calls, [])

    def test_a_second_sign_in_started_before_the_first_returned_ends_neither(self) -> None:
        # Another tab, or the session cover's sign-in, starts a sign-in while the first is still at Eneo.
        first, _ = self.start_login()
        second, _ = self.start_login()
        self.assertEqual(len(pending_logins(self.client.cookies)), 2)

        for state in (first, second):
            with self.subTest(state=state):
                callback = self.client.get("/api/auth/callback", params={"ticket": "one-time-ticket", "state": state})
                self.assertEqual(callback.headers["location"], "/flows")
                self.assertIn(SESSION_COOKIE, callback.cookies)
        self.assertEqual(pending_logins(self.client.cookies), {}, "each callback clears its own state")

    def test_at_most_five_sign_ins_wait_and_a_sixth_drops_the_oldest(self) -> None:
        start = time.time()
        states = []
        for second in range(6):
            with patch("time.time", return_value=start + second):
                states.append(self.start_login()[0])
        self.assertEqual(len(pending_logins(self.client.cookies)), 5)
        self.assertNotIn(state_cookie_name(states[0]), self.client.cookies)

        with patch("time.time", return_value=start + 10):
            oldest = self.client.get("/api/auth/callback", params={"ticket": "one-time-ticket", "state": states[0]})
            self.assertEqual(oldest.headers["location"], "/?auth_error=invalid_state")
            self.assertEqual(self.exchange_client.calls, [])
            newest = self.client.get("/api/auth/callback", params={"ticket": "one-time-ticket", "state": states[5]})
            self.assertEqual(newest.headers["location"], "/flows")

    def test_two_sign_ins_started_at_once_overshoot_the_five_only_until_the_next_start(self) -> None:
        # Two starts sent before either answer lands both see the same four waiting logins: the five is a cleanup target
        # that the next start restores, not a lock across requests.
        start = time.time()
        waiting: dict[str, str] = {}
        for second in range(4):
            with patch("time.time", return_value=start + second):
                waiting |= pending_logins(self.client.get("/api/auth/login", headers=cookie_header(waiting)).cookies)
        with patch("time.time", return_value=start + 4):
            both = [self.client.get("/api/auth/login", headers=cookie_header(waiting)) for _ in range(2)]
        for response in both:
            self.assertNotIn("Max-Age=0", str(response.headers.get_list("set-cookie")))
            waiting |= pending_logins(response.cookies)
        self.assertEqual(len(waiting), 6)

        with patch("time.time", return_value=start + 5):
            next_start = self.client.get("/api/auth/login", headers=cookie_header(waiting))

        dropped = [cookie for cookie in next_start.headers.get_list("set-cookie") if "Max-Age=0" in cookie]
        self.assertEqual(len(dropped), 2, "the two oldest go, so five wait again")
        self.assertTrue(all(any(cookie.startswith(f"{name}=") for name in list(waiting)[:2]) for cookie in dropped))

    def test_a_cookie_the_module_never_set_is_no_waiting_login_and_breaks_no_login(self) -> None:
        # Another site on the parent domain can set cookies with any name; a name the module could not have set is ignored.
        foreign = {f"{STATE_COOKIE}_{name}": "x" for name in ("@", "a", "b", "c", "d", "e" * 24)}

        response = self.client.get("/api/auth/login", headers=cookie_header(foreign))

        self.assertEqual(response.status_code, 303)
        self.assertNotIn("Max-Age=0", response.headers["set-cookie"], "nothing it did not set is deleted")

    def test_a_callback_reads_only_its_own_login_s_state(self) -> None:
        # A renewal binds the new login to the page's user. Another login waiting beside it, which binds no one, never
        # admits the renewal's callback for someone else.
        self.sign_in()
        renewal = self.start_renewal()
        plain, _ = self.start_login()
        self.exchange_client.response = FakeResponse(user_id="someone-else")
        self.exchange_client.validation_response = FakeResponse(user_id="someone-else")

        callback = self.client.get("/api/auth/callback", params={"ticket": "other-user", "state": renewal})

        self.assertEqual(callback.headers["location"], "/inloggad?fel=annan-anvandare")
        self.assertNotIn(SESSION_COOKIE, callback.cookies)
        self.assertEqual(self.client.get("/api/auth/status").json()["user"]["id"], "user-id")
        self.assertEqual(list(pending_logins(self.client.cookies)), [state_cookie_name(plain)], "the other login waits on")

    def test_the_state_cookie_of_a_login_before_this_version_is_ignored(self) -> None:
        # One cookie under the old fixed name: a login started before an upgrade fails once as invalid_state.
        legacy = self.client.get("/api/auth/login")
        state = parse_qs(urlparse(legacy.headers["location"]).query)["state"][0]
        [value] = pending_logins(legacy.cookies).values()
        self.client.cookies.clear()

        callback = self.client.get(
            "/api/auth/callback", params={"ticket": "one-time-ticket", "state": state}, headers={"Cookie": f"{STATE_COOKIE}={value}"}
        )

        self.assertEqual(callback.headers["location"], "/?auth_error=invalid_state")
        self.assertEqual(self.exchange_client.calls, [])

    def test_callback_state_is_consumed_after_success(self) -> None:
        state, _ = self.start_login()
        first = self.client.get(
            "/api/auth/callback",
            params={"ticket": "one-time-ticket", "state": state},
        )
        second = self.client.get(
            "/api/auth/callback",
            params={"ticket": "replayed-ticket", "state": state},
        )

        self.assertEqual(first.headers["location"], "/flows")
        self.assertEqual(second.headers["location"], "/?auth_error=invalid_state")
        self.assertEqual(len(self.exchange_client.calls), 2)

    def test_a_session_end_without_a_time_zone_is_read_as_utc(self) -> None:
        # Read as local time, Europe/Stockholm would end every session two hours early (one in winter).
        original = os.environ.get("TZ")
        self.addCleanup(self.restore_time_zone, original)
        os.environ["TZ"] = "Europe/Stockholm"
        time.tzset()
        self.exchange_client.response = FakeResponse(naive=True)
        self.exchange_client.validation_response = FakeResponse(naive=True)
        state, _ = self.start_login()

        self.client.get("/api/auth/callback", params={"ticket": "one-time-ticket", "state": state})

        body = self.client.get("/api/auth/status").json()
        self.assertTrue(ENEO_SESSION_SECONDS - 5 <= body["session_ends_in"] <= ENEO_SESSION_SECONDS, body)

    @staticmethod
    def restore_time_zone(original: str | None) -> None:
        if original is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original
        time.tzset()

    def test_a_state_that_is_not_ascii_is_refused_not_a_500(self) -> None:
        self.start_login()

        callback = self.client.get(
            "/api/auth/callback",
            params={"ticket": "one-time-ticket", "state": "tillstånd"},
        )

        self.assertEqual(callback.status_code, 303)
        self.assertEqual(callback.headers["location"], "/?auth_error=invalid_state")
        self.assertEqual(self.exchange_client.calls, [])

    def test_a_second_login_ends_the_session_the_browser_already_holds(self) -> None:
        first = self.sign_in()
        state, _ = self.start_login()

        callback = self.client.get("/api/auth/callback", params={"ticket": "second", "state": state})

        second = callback.cookies[SESSION_COOKIE]
        self.assertNotEqual(second, first)
        self.assertIsNone(self.auth.sessions.get(first), "two sessions must not stay alive for one browser")
        self.assertIsNotNone(self.auth.sessions.get(second))

    def test_a_renewal_by_the_same_user_ends_the_old_session(self) -> None:
        first = self.sign_in()
        state = self.start_renewal()

        callback = self.client.get("/api/auth/callback", params={"ticket": "again", "state": state})

        self.assertIsNone(self.auth.sessions.get(first))
        self.assertIsNotNone(self.auth.sessions.get(callback.cookies[SESSION_COOKIE]))

    def test_a_login_that_fails_leaves_the_session_the_browser_holds(self) -> None:
        first = self.sign_in()
        state, _ = self.start_login()
        self.exchange_client.response = FakeResponse(status_code=401)

        callback = self.client.get("/api/auth/callback", params={"ticket": "bad", "state": state})

        self.assertEqual(callback.headers["location"], "/?auth_error=exchange_failed")
        self.assertIsNotNone(self.auth.sessions.get(first))

    def test_status_says_when_the_session_ends(self) -> None:
        state, _ = self.start_login()
        self.client.get("/api/auth/callback", params={"ticket": "one-time-ticket", "state": state})

        body = self.client.get("/api/auth/status").json()

        # Eneo's 4-hour ceiling, not the 15-minute token: the page warns before it.
        self.assertTrue(ENEO_SESSION_SECONDS - 5 <= body["session_ends_in"] <= ENEO_SESSION_SECONDS)

    def test_a_login_can_return_to_a_page_of_the_module(self) -> None:
        response = self.client.get("/api/auth/login", params={"next": "/inloggad"})
        state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]

        callback = self.client.get(
            "/api/auth/callback",
            params={"ticket": "one-time-ticket", "state": state},
        )

        self.assertEqual(callback.headers["location"], "/inloggad")

    def test_a_login_never_returns_outside_the_module(self) -> None:
        for unsafe in ("https://evil.example", "//evil.example", "/\\evil.example", "inloggad"):
            with self.subTest(next=unsafe):
                response = self.client.get("/api/auth/login", params={"next": unsafe})
                state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]

                callback = self.client.get(
                    "/api/auth/callback",
                    params={"ticket": "one-time-ticket", "state": state},
                )

                self.assertEqual(callback.headers["location"], "/flows")

    def test_a_finished_login_whose_next_holds_a_control_character_lands_on_the_home_path(self) -> None:
        # The rule against control characters in next holds with a state cookie per login, also while others wait.
        self.start_login()
        for label, value in VECTORS.items():
            with self.subTest(label):
                response = self.client.get("/api/auth/login", params={"next": value})
                state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]

                callback = self.client.get("/api/auth/callback", params={"ticket": "one-time-ticket", "state": state})

                self.assertEqual(callback.headers["location"], "/flows")
        self.assertEqual(len(pending_logins(self.client.cookies)), 1, "the login started first still waits")

    def test_a_next_above_512_characters_falls_back_to_the_home_path(self) -> None:
        # 6 000 characters make a state cookie of 8 KB, which browsers drop: the login would fail as invalid_state.
        for length, lands_on_next in ((512, True), (513, False), (6000, False)):
            with self.subTest(length=length):
                # Random, because the signed state is compressed: a repeated character would hide the size.
                long_next = "/" + secrets.token_urlsafe(length)[: length - 1]
                login = self.client.get("/api/auth/login", params={"next": long_next})
                state_cookie = next(h for h in login.headers.get_list("set-cookie") if h.startswith(f"{STATE_COOKIE}_"))
                self.assertLess(len(state_cookie), 4096)
                state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]

                callback = self.client.get("/api/auth/callback", params={"ticket": "one-time-ticket", "state": state})

                self.assertEqual(callback.headers["location"], long_next if lands_on_next else "/flows")

    def test_six_waiting_logins_stay_under_a_proxy_s_8_kb_header_whatever_their_next(self) -> None:
        # Every waiting login's cookie goes with every /api/auth request, the status calls too: a long next in each could
        # push the Cookie header past a proxy's limit (ingress-nginx: 8 KB) and lock the browser out of signing in until
        # they expire. Six, as two starts at once can leave. The bound is the signed cookie's bytes, not next's
        # characters. Varied characters: the signed payload is compressed, and a repeated one would hide the size.
        varied = lambda first, count: "/" + "".join(chr(first + i) for i in range(count))
        for kind, next_path in (("ascii", "/" + secrets.token_urlsafe(600)[:511]), ("cjk", varied(0x4E00, 511)), ("emoji", varied(0x1F300, 511))):
            with self.subTest(kind=kind):
                waiting: dict[str, str] = {}
                for _ in range(4):
                    waiting |= pending_logins(self.client.get("/api/auth/login", params={"next": next_path}, headers=cookie_header(waiting)).cookies)
                four = cookie_header(waiting)
                for _ in range(2):
                    waiting |= pending_logins(self.client.get("/api/auth/login", params={"next": next_path}, headers=four).cookies)
                self.assertEqual(len(waiting), 6)
                self.assertTrue(all(len(value.encode()) <= MAX_STATE_COOKIE_BYTES for value in waiting.values()))
                self.assertLessEqual(len(cookie_header(waiting)["Cookie"].encode()), 8 * 1024)
                self.client.cookies.clear()

        response = self.client.get("/api/auth/login", params={"next": "/flows/a?run=r1"})
        state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
        callback = self.client.get("/api/auth/callback", params={"ticket": "one-time-ticket", "state": state})
        self.assertEqual(callback.headers["location"], "/flows/a?run=r1", "an ordinary next is kept")

    def test_a_next_whose_signed_state_passes_the_byte_bound_lands_on_the_home_path(self) -> None:
        # 511 characters pass MAX_NEXT_LENGTH, but as CJK they sign to more than MAX_STATE_COOKIE_BYTES.
        long_next = "/" + "".join(chr(0x4E00 + i) for i in range(510))
        login = self.client.get("/api/auth/login", params={"next": long_next})
        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]

        callback = self.client.get("/api/auth/callback", params={"ticket": "one-time-ticket", "state": state})

        self.assertEqual(callback.headers["location"], "/flows")

    def test_a_renewal_whose_signed_state_would_pass_the_byte_bound_is_refused_not_sent(self) -> None:
        # Eneo's ids are UUIDs, which start-up counts on; an id far longer than that cannot make a cookie over the bound.
        session_id = self.auth.sessions.create(
            ModuleSession(
                access_token="t", expires_at=int(time.time()) + 600, refresh_at=int(time.time()) + 300,
                session_expires_at=int(time.time()) + 3600, module_key="speech-to-text", tenant_id="tenant-id",
                user=ModuleUser(id=secrets.token_urlsafe(1200), email="user@example.test"),
            )
        )
        self.client.cookies.set(SESSION_COOKIE, session_id)

        with self.assertRaisesRegex(RuntimeError, "MAX_STATE_COOKIE_BYTES"):
            self.client.get("/api/auth/login", params={"renew": "1", "next": "/inloggad"})

    def test_the_signal_for_the_page_goes_before_a_fragment(self) -> None:
        self.assertEqual(with_query("/page", "fel=x"), "/page?fel=x")
        self.assertEqual(with_query("/page?a=1", "fel=x"), "/page?a=1&fel=x")
        self.assertEqual(with_query("/page#top", "fel=x"), "/page?fel=x#top")
        self.assertEqual(with_query("/page?a=1#top", "fel=x"), "/page?a=1&fel=x#top")

    def test_a_renewal_by_another_user_signals_the_page_even_when_next_has_a_fragment(self) -> None:
        self.sign_in()
        response = self.client.get("/api/auth/login", params={"renew": "1", "next": "/inloggad#top"})
        state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
        self.exchange_client.response = FakeResponse(user_id="someone-else")
        self.exchange_client.validation_response = FakeResponse(user_id="someone-else")

        callback = self.client.get("/api/auth/callback", params={"ticket": "other-user", "state": state})

        self.assertEqual(callback.headers["location"], "/inloggad?fel=annan-anvandare#top")

    def test_a_refused_renewal_signals_the_page_even_when_next_has_a_fragment(self) -> None:
        response = self.client.get("/api/auth/login", params={"renew": "1", "next": "/inloggad#top"})

        self.assertEqual(response.headers["location"], "/inloggad?fel=utgangen#top")

    def sign_in(self) -> str:
        state, _ = self.start_login()
        callback = self.client.get("/api/auth/callback", params={"ticket": "first", "state": state})
        return callback.cookies[SESSION_COOKIE]

    def start_renewal(self) -> str:
        response = self.client.get("/api/auth/login", params={"renew": "1", "next": "/inloggad"})
        return parse_qs(urlparse(response.headers["location"]).query)["state"][0]

    def test_a_renewal_by_the_same_user_replaces_the_session(self) -> None:
        first = self.sign_in()
        state = self.start_renewal()

        callback = self.client.get("/api/auth/callback", params={"ticket": "again", "state": state})

        self.assertEqual(callback.headers["location"], "/inloggad")
        self.assertNotEqual(callback.cookies[SESSION_COOKIE], first)

    def test_a_renewal_by_another_user_keeps_the_page_s_session(self) -> None:
        first = self.sign_in()
        state = self.start_renewal()
        self.exchange_client.response = FakeResponse(user_id="someone-else")
        self.exchange_client.validation_response = FakeResponse(user_id="someone-else")

        callback = self.client.get("/api/auth/callback", params={"ticket": "other-user", "state": state})

        self.assertEqual(callback.headers["location"], "/inloggad?fel=annan-anvandare")
        self.assertNotIn(SESSION_COOKIE, callback.cookies)
        self.assertEqual(self.client.cookies.get(SESSION_COOKIE), first)
        self.assertEqual(self.client.get("/api/auth/status").json()["user"]["id"], "user-id")

    def older_login_callback(self, stored_next: str, *, renew: bool = False, ticket: str = "one-time-ticket"):
        """The callback of a login started before an upgrade: its state, signed with the same secret, holds the
        destination the earlier build accepted (its home path, when the login came with no usable next). The state
        cookie goes in the client's jar, beside the browser's session, as a browser sends it."""
        state = secrets.token_urlsafe(32)
        login = PendingLogin(
            state=state,
            next=stored_next,
            renew_user_id="user-id" if renew else None,
            renew_tenant_id="tenant-id" if renew else None,
        )
        self.client.cookies.set(state_cookie_name(state), self.auth.state_serializer.dumps(login.model_dump()))
        return self.client.get("/api/auth/callback", params={"ticket": ticket, "state": state})

    def test_a_login_started_under_a_home_path_this_release_refuses_still_signs_in_to_the_current_home_path(self) -> None:
        # A build with a login state cookie per login, restarted with a corrected home path and the same secret: the
        # sign-in under way still arrives, inside the module. A valid signature says who wrote the destination, not that
        # it is still a path of the module.
        for stored in ("//elsewhere.example", "/\\elsewhere.example", "flows", ""):
            with self.subTest(stored=stored):
                exchanges = len([call for call in self.exchange_client.calls if call["method"] == "POST"])

                callback = self.older_login_callback(stored)

                self.assertEqual(callback.status_code, 303)
                self.assertEqual(callback.headers["location"], "/flows")
                self.assertIn(SESSION_COOKIE, callback.cookies)
                self.assertEqual(len([call for call in self.exchange_client.calls if call["method"] == "POST"]), exchanges + 1)
                self.assertTrue(
                    any(cookie.startswith(f"{STATE_COOKIE}_") and "Max-Age=0" in cookie for cookie in callback.headers.get_list("set-cookie")),
                    "its state cookie is deleted",
                )

    def test_a_renewal_by_another_user_started_under_a_refused_home_path_is_refused_on_the_current_home_path(self) -> None:
        first = self.sign_in()
        self.exchange_client.response = FakeResponse(user_id="someone-else")
        self.exchange_client.validation_response = FakeResponse(user_id="someone-else")

        callback = self.older_login_callback("//elsewhere.example", renew=True, ticket="other-user")

        self.assertEqual(callback.headers["location"], "/flows?fel=annan-anvandare")
        self.assertNotIn(SESSION_COOKIE, callback.cookies)
        self.assertEqual(self.client.cookies.get(SESSION_COOKIE), first)
        self.assertEqual(self.client.get("/api/auth/status").json()["user"]["id"], "user-id", "the session still works")

    def test_a_valid_destination_of_a_login_started_before_an_upgrade_keeps_its_meaning(self) -> None:
        for stored in ("/", "/reports?x=1#top"):
            with self.subTest(stored=stored):
                callback = self.older_login_callback(stored)

                self.assertEqual(callback.headers["location"], stored)
                self.assertIn(SESSION_COOKIE, callback.cookies)

    def test_a_renewal_without_a_live_session_is_refused_and_signs_no_one_in(self) -> None:
        self.sign_in()
        ended = time.time() + ENEO_SESSION_SECONDS + 60
        for case, cookies in (("the session has ended", None), ("no session at all", {})):
            with self.subTest(case), patch("eneo_module_bff.auth.time.time", return_value=ended):
                if cookies is not None:
                    self.client.cookies.clear()
                response = self.client.get("/api/auth/login", params={"renew": "1", "next": "/inloggad"})

                # No handoff to Eneo: with no user to bind to, anyone could sign in under this page.
                self.assertEqual(response.status_code, 303)
                self.assertEqual(response.headers["location"], "/inloggad?fel=utgangen")
                self.assertEqual(pending_logins(response.cookies), {})
                self.assertNotIn(SESSION_COOKIE, response.cookies)

    def test_failed_exchange_redirects_without_creating_session(self) -> None:
        self.exchange_client.response = FakeResponse(status_code=401)
        state, _ = self.start_login()

        callback = self.client.get(
            "/api/auth/callback",
            params={"ticket": "bad-ticket", "state": state},
        )

        self.assertEqual(callback.headers["location"], "/?auth_error=exchange_failed")
        self.assertNotIn("eneo_module_session", callback.cookies)
        self.assertEqual(
            self.client.get("/api/auth/status").json(),
            {
                "authenticated": False,
                "user": None,
            },
        )

    def test_failed_dual_auth_validation_does_not_create_session(self) -> None:
        self.exchange_client.validation_response = FakeResponse(status_code=403)
        state, _ = self.start_login()

        callback = self.client.get(
            "/api/auth/callback",
            params={"ticket": "one-time-ticket", "state": state},
        )

        self.assertEqual(callback.headers["location"], "/?auth_error=validation_failed")
        self.assertNotIn(SESSION_COOKIE, callback.cookies)
        self.assertEqual(len(self.exchange_client.calls), 2)

    def test_protected_endpoint_rejects_missing_session(self) -> None:
        response = self.client.get("/resource")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["x-auth-required"], "session")

    def test_logout_rejects_cross_origin_request(self) -> None:
        response = self.client.post(
            "/api/auth/logout",
            headers={"Origin": "https://attacker.example.test"},
        )

        self.assertEqual(response.status_code, 403)

    def test_logout_revokes_the_opaque_session(self) -> None:
        state, _ = self.start_login()
        callback = self.client.get(
            "/api/auth/callback",
            params={"ticket": "one-time-ticket", "state": state},
        )
        session_id = callback.cookies[SESSION_COOKIE]

        response = self.client.post(
            "/api/auth/logout",
            headers={"Origin": "https://module.example.test"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.auth.sessions.get(session_id))
        self.assertEqual(
            self.client.get("/api/auth/status").json(),
            {
                "authenticated": False,
                "user": None,
            },
        )


class Clock:
    """Stands in for the time module inside eneo_module_bff.auth: wall time and the monotonic clock move together."""

    def __init__(self) -> None:
        self.now = time.time()
        self.monotonic_now = 1000.0

    def time(self) -> float:
        return self.now

    def monotonic(self) -> float:
        return self.monotonic_now

    def advance(self, seconds: float) -> None:
        self.now += seconds
        self.monotonic_now += seconds


class ModuleSessionStoreTests(unittest.TestCase):
    """The signed URLs minted for a session are kept by the store, for the life of that session."""

    def session(self, lasts: int = 3600) -> ModuleSession:
        now = int(time.time())
        return ModuleSession(
            access_token="token", expires_at=now + lasts, refresh_at=now + lasts // 2, session_expires_at=now + lasts,
            module_key="m", tenant_id="t", user=ModuleUser(id="u", email="u@example.test"),
        )

    def url(self, lasts: int = 900) -> SignedUrl:
        return SignedUrl(url="http://eneo/file?token=x", expires_at=time.time() + lasts)

    def test_get_refuses_an_expired_session_itself_between_sweeps_and_drops_its_signed_urls(self) -> None:
        clock = Clock()
        with patch("eneo_module_bff.auth.time", clock):
            store = ModuleSessionStore()
            short, other_short, long = store.create(self.session(lasts=5)), store.create(self.session(lasts=5)), store.create(self.session(lasts=3600))
            store.remember_signed_url(short, "files/a/", self.url())
            clock.advance(10)  # both short sessions have expired, and the last sweep was 10 s ago: none is due

            self.assertIsNone(store.get(short))

            self.assertIsNone(store.signed_url(short, "files/a/"))
            self.assertNotIn(short, store._signed_urls)
            self.assertIn(other_short, store._sessions, "no sweep ran: get() did not scan the store to refuse one id")
            self.assertIsNotNone(store.get(long))

    def test_expired_sessions_and_their_tokens_are_swept_once_the_window_has_passed(self) -> None:
        clock = Clock()
        with patch("eneo_module_bff.auth.time", clock):
            store = ModuleSessionStore()
            expiring = [store.create(self.session(lasts=5)) for _ in range(50)]
            long = store.create(self.session(lasts=3600))
            store.remember_signed_url(expiring[0], "files/a/", self.url())
            clock.advance(31)

            store.get("not-a-session")  # any request notices the window has passed

            self.assertEqual(set(store._sessions), {long}, "the tokens of the expired sessions are no longer held")
            self.assertEqual(store._signed_urls, {})

    def test_the_sweep_runs_once_per_window_not_once_per_call(self) -> None:
        clock = Clock()
        with patch("eneo_module_bff.auth.time", clock):
            store = ModuleSessionStore()
            first = store.create(self.session(lasts=3600))  # the first call sweeps, and the next sweep is 30 s away
            clock.advance(1)
            doomed = store.create(self.session(lasts=0))  # expires at once
            for _ in range(5):
                store.get(first)
            self.assertIn(doomed, store._sessions, "swept inside the window")

            clock.advance(30)  # 31 s after the last sweep
            store.get(first)

            self.assertNotIn(doomed, store._sessions)
            clock.advance(1)
            again = store.create(self.session(lasts=0))
            store.get(first)
            self.assertIn(again, store._sessions, "and the next window has started")

    def test_a_get_and_a_create_do_not_scan_every_session(self) -> None:
        # Measured at 10 000 sessions: 340 us per get, and 380 us per create, when each scanned all of them.
        store = ModuleSessionStore()
        for _ in range(10_000):
            store.create(self.session())

        get = min(timeit.repeat(lambda: store.get("not-a-session"), number=200, repeat=7)) / 200
        create = min(timeit.repeat(lambda: store.create(self.session()), number=50, repeat=7)) / 50

        self.assertLess(get, 100e-6, f"get took {get * 1e6:.0f} us")
        self.assertLess(create, 100e-6, f"create took {create * 1e6:.0f} us")

    def test_a_signed_url_is_kept_for_a_live_session(self) -> None:
        store = ModuleSessionStore()
        session_id = store.create(self.session())

        store.remember_signed_url(session_id, "files/a/", self.url())

        self.assertEqual(store.signed_url(session_id, "files/a/").url, "http://eneo/file?token=x")
        self.assertIsNone(store.signed_url(session_id, "files/b/"))
        self.assertIsNone(store.signed_url("someone-else", "files/a/"))

    def test_deleting_a_session_deletes_its_signed_urls(self) -> None:
        store = ModuleSessionStore()
        first, second = store.create(self.session()), store.create(self.session())
        store.remember_signed_url(first, "files/a/", self.url())
        store.remember_signed_url(second, "files/a/", self.url())

        store.delete(first)

        self.assertIsNone(store.signed_url(first, "files/a/"))
        self.assertIsNotNone(store.signed_url(second, "files/a/"))
        self.assertEqual(set(store._signed_urls), {second})

    def test_an_expired_session_takes_its_signed_urls_with_it(self) -> None:
        clock = Clock()
        with patch("eneo_module_bff.auth.time", clock):
            store = ModuleSessionStore()
            short, long = store.create(self.session(lasts=60)), store.create(self.session(lasts=3600))
            store.remember_signed_url(short, "files/a/", self.url())
            store.remember_signed_url(long, "files/a/", self.url())
            clock.advance(120)  # past the sweep window as well as past the short session

            self.assertIsNotNone(store.get(long))  # a use of the store after the window sweeps the expired session

        self.assertEqual(set(store._signed_urls), {long})

    def test_an_expired_session_asked_for_directly_drops_its_signed_urls(self) -> None:
        store = ModuleSessionStore()
        session_id = store.create(self.session(lasts=60))
        store.remember_signed_url(session_id, "files/a/", self.url())

        with patch("eneo_module_bff.auth.time.time", return_value=time.time() + 120):
            self.assertIsNone(store.get(session_id))

        self.assertEqual(store._signed_urls, {})

    def test_clearing_the_store_clears_the_signed_urls(self) -> None:
        store = ModuleSessionStore()
        session_id = store.create(self.session())
        store.remember_signed_url(session_id, "files/a/", self.url())

        store.clear()

        self.assertEqual(store._signed_urls, {})

    def test_a_signed_url_is_not_kept_for_a_session_that_is_gone(self) -> None:
        # A logout can arrive while Eneo is still answering the mint request.
        store = ModuleSessionStore()
        session_id = store.create(self.session())
        store.delete(session_id)

        store.remember_signed_url(session_id, "files/a/", self.url())

        self.assertEqual(store._signed_urls, {})

    def test_a_signed_url_that_has_expired_is_pruned_when_another_is_kept(self) -> None:
        store = ModuleSessionStore()
        session_id = store.create(self.session())
        store.remember_signed_url(session_id, "files/old/", SignedUrl("http://eneo/old", time.time() - 1))

        store.remember_signed_url(session_id, "files/new/", self.url())

        self.assertEqual(set(store._signed_urls[session_id]), {"files/new/"})

    def test_a_forgotten_signed_url_is_gone_and_leaves_no_empty_entry(self) -> None:
        store = ModuleSessionStore()
        session_id = store.create(self.session())
        store.remember_signed_url(session_id, "files/a/", self.url())

        store.forget_signed_url(session_id, "files/a/")
        store.forget_signed_url(session_id, "files/never/")
        store.forget_signed_url("someone-else", "files/a/")

        self.assertEqual(store._signed_urls, {})


class FakeEneo:
    """Eneo's token refresh route plus any proxied resource call."""

    def __init__(self, refresh) -> None:
        # A response, an exception to raise, or an async function answering the call.
        self.refresh = refresh
        self.refresh_calls: list[dict[str, object]] = []
        self.proxied: list[dict[str, object]] = []

    async def post(self, url: str, **kwargs):
        self.refresh_calls.append({"url": url, **kwargs})
        if isinstance(self.refresh, Exception):
            raise self.refresh
        if callable(self.refresh):
            return await self.refresh(**kwargs)
        return self.refresh

    async def request(self, **kwargs):
        self.proxied.append(kwargs)
        return httpx2.Response(200, json={"items": []})


class FakeClock:
    """Stands in for the time module inside eneo_module_bff.auth."""

    def __init__(self) -> None:
        self.now = time.time()

    def time(self) -> float:
        return self.now

    def monotonic(self) -> float:
        return self.now


class TokenRefreshFixture:
    """Sessions whose module token is due for renewal, and a fake Eneo."""

    def setUp(self) -> None:
        # The fake Eneo that answers comes with use_eneo, before the first request.
        self.app, self.auth = build_auth(FakeEneo(None))
        self.client = TestClient(self.app)

    def sign_in_with_due_token(
        self, token: str = "module-user-token", *, expires_in: int = 100
    ) -> str:
        """A session past its token's half-life, the token itself still valid."""
        now = int(time.time())
        session_id = self.auth.sessions.create(
            ModuleSession(
                access_token=token,
                expires_at=now + expires_in,
                refresh_at=now - 1,
                session_expires_at=now + 3600,
                module_key="speech-to-text",
                tenant_id="tenant-id",
                user=ModuleUser(id="user-id", email="user@example.test"),
            )
        )
        self.client.cookies.set(SESSION_COOKIE, session_id)
        return session_id

    def use_eneo(self, refresh) -> FakeEneo:
        eneo = FakeEneo(refresh)
        self.auth.http_client = eneo
        self.app.state.http = eneo
        return eneo


class ModuleTokenRefreshTests(TokenRefreshFixture, unittest.TestCase):

    def test_due_token_is_refreshed_before_the_request_is_proxied(self) -> None:
        session_id = self.sign_in_with_due_token()
        eneo = self.use_eneo(
            httpx2.Response(200, json=token_payload("refreshed-token", expires_in=900))
        )
        before = int(time.time())

        response = self.client.get("/resource")

        after = int(time.time())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(eneo.refresh_calls), 1)
        refresh = eneo.refresh_calls[0]
        self.assertEqual(
            refresh["url"],
            "https://eneo.example.test/api/v1/module-auth/speech-to-text/token/refresh/",
        )
        self.assertEqual(
            refresh["headers"],
            {"X-API-Key": "test-key", "Authorization": "Bearer module-user-token"},
        )
        self.assertEqual(
            eneo.proxied[0]["headers"]["Authorization"], "Bearer refreshed-token"
        )
        session = self.auth.sessions.get(session_id)
        self.assertEqual(session.access_token, "refreshed-token")
        self.assertTrue(before + 900 <= session.expires_at <= after + 900)
        self.assertTrue(before + 450 <= session.refresh_at <= after + 450)

        # The renewed token is not due, so the next request goes straight through.
        self.client.get("/resource")
        self.assertEqual(len(eneo.refresh_calls), 1)
        self.assertEqual(
            eneo.proxied[1]["headers"]["Authorization"], "Bearer refreshed-token"
        )

    def test_refused_refresh_ends_the_session(self) -> None:
        refusals = {
            "expired or past the ceiling": httpx2.Response(401),
            "key no longer bound": httpx2.Response(403),
            "module removed": httpx2.Response(404),
            "another user's token": httpx2.Response(
                200, json=token_payload("other-token", user_id="other-user")
            ),
        }
        for reason, refresh in refusals.items():
            with self.subTest(reason):
                session_id = self.sign_in_with_due_token()
                eneo = self.use_eneo(refresh)

                response = self.client.get("/resource")

                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["x-auth-required"], "session")
                self.assertEqual(eneo.proxied, [])
                self.assertIsNone(self.auth.sessions.get(session_id))
                self.assertFalse(
                    self.client.get("/api/auth/status").json()["authenticated"]
                )

    def test_unavailable_eneo_keeps_the_still_valid_token(self) -> None:
        for refresh in (httpx2.Response(503), httpx2.ConnectError("unreachable")):
            with self.subTest(refresh=refresh):
                session_id = self.sign_in_with_due_token()
                eneo = self.use_eneo(refresh)

                response = self.client.get("/resource")

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    eneo.proxied[0]["headers"]["Authorization"],
                    "Bearer module-user-token",
                )
                self.assertIsNotNone(self.auth.sessions.get(session_id))

    def test_an_unexpected_error_while_refreshing_keeps_the_token_and_asks_again_later(self) -> None:
        # Not an answer from Eneo (a bug, or a library error): it must not become a 500 on every request.
        session_id = self.sign_in_with_due_token()
        eneo = self.use_eneo(RuntimeError("boom"))

        with self.assertLogs("eneo_module_auth", level="ERROR"):
            response = self.client.get("/resource")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(eneo.proxied[0]["headers"]["Authorization"], "Bearer module-user-token")
        self.assertIsNotNone(self.auth.sessions.get(session_id))
        # It asks again shortly, not on the very next request.
        self.assertEqual(self.client.get("/resource").status_code, 200)
        self.assertEqual(len(eneo.refresh_calls), 1)
        self.assertEqual(self.auth._refreshes, {})

    def test_a_refresh_that_ends_the_session_drops_its_signed_urls(self) -> None:
        session_id = self.sign_in_with_due_token()
        self.auth.sessions.remember_signed_url(session_id, "files/a/", SignedUrl("http://eneo/f", time.time() + 900))
        self.use_eneo(httpx2.Response(401))

        self.assertEqual(self.client.get("/resource").status_code, 401)

        self.assertIsNone(self.auth.sessions.get(session_id))
        self.assertEqual(self.auth.sessions._signed_urls, {})

    def test_status_check_refreshes_an_idle_session(self) -> None:
        # The browser polls the status while it records, which sends no other request.
        session_id = self.sign_in_with_due_token()
        eneo = self.use_eneo(
            httpx2.Response(200, json=token_payload("refreshed-token", expires_in=900))
        )

        status = self.client.get("/api/auth/status")

        self.assertTrue(status.json()["authenticated"])
        self.assertEqual(len(eneo.refresh_calls), 1)
        self.assertEqual(
            self.auth.sessions.get(session_id).access_token, "refreshed-token"
        )

    def test_renewal_that_outlasts_the_token_ends_the_session(self) -> None:
        clock = FakeClock()

        async def refresh(**_):
            clock.now += 6  # Eneo answers only after the token has expired.
            return httpx2.Response(503)

        with patch("eneo_module_bff.auth.time", clock):
            session_id = self.sign_in_with_due_token(expires_in=5)
            eneo = self.use_eneo(refresh)

            response = self.client.get("/resource")

            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.headers["x-auth-required"], "session")
            self.assertEqual(eneo.proxied, [])
            self.assertIsNone(self.auth.sessions.get(session_id))

    def test_one_minute_token_is_kept_alive_on_the_status_schedule(self) -> None:
        # Eneo accepts MODULE_AUTH_TOKEN_EXPIRY_MINUTES=1. The page asks for the
        # status again `refresh_in` seconds after each answer.
        clock = FakeClock()
        renewals = itertools.count(1)

        async def refresh(**_):
            token = f"token-{next(renewals)}"
            return httpx2.Response(200, json=token_payload(token, expires_in=60))

        with patch("eneo_module_bff.auth.time", clock):
            now = int(clock.now)
            session_id = self.auth.sessions.create(
                ModuleSession(
                    access_token="token-0",
                    expires_at=now + 60,
                    refresh_at=now + 30,
                    session_expires_at=now + 3600,
                    module_key="speech-to-text",
                    tenant_id="tenant-id",
                    user=ModuleUser(id="user-id", email="user@example.test"),
                )
            )
            self.client.cookies.set(SESSION_COOKIE, session_id)
            eneo = self.use_eneo(refresh)

            status = self.client.get("/api/auth/status").json()
            for _ in range(4):  # four minutes on a one-minute token
                clock.now += status["refresh_in"] + 1
                status = self.client.get("/api/auth/status").json()
                self.assertTrue(status["authenticated"])

        self.assertEqual(len(eneo.refresh_calls), 4)


class ConcurrentTokenRefreshTests(TokenRefreshFixture, unittest.IsolatedAsyncioTestCase):
    async def get_flows(self, session_id: str) -> httpx2.Response:
        transport = httpx2.ASGITransport(app=self.app)
        async with httpx2.AsyncClient(
            transport=transport, base_url="http://module.test"
        ) as client:
            return await client.get(
                "/resource",
                headers={"Cookie": f"{SESSION_COOKIE}={session_id}"},
            )

    async def test_a_stalled_renewal_does_not_hold_up_another_session(self) -> None:
        stalled = self.sign_in_with_due_token("stalled-token")
        other = self.sign_in_with_due_token("other-token")
        started, release = asyncio.Event(), asyncio.Event()

        async def refresh(headers, **_):
            token = headers["Authorization"].removeprefix("Bearer ")
            if token == "stalled-token":
                started.set()
                await release.wait()
            return httpx2.Response(200, json=token_payload(f"renewed-{token}"))

        eneo = self.use_eneo(refresh)
        waiting = asyncio.create_task(self.get_flows(stalled))
        await started.wait()

        # The other session's request is answered while the stalled renewal still waits: the order proves it, not the
        # clock. The bound only turns a request held behind the stalled one into a failure instead of a hang; a shared
        # CI runner once took more than 2 s for the answer.
        response = await asyncio.wait_for(self.get_flows(other), timeout=10)
        self.assertFalse(release.is_set())
        self.assertFalse(waiting.done(), "the stalled session's request is still waiting for its renewal")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            eneo.proxied[-1]["headers"]["Authorization"], "Bearer renewed-other-token"
        )
        release.set()
        self.assertEqual((await waiting).status_code, 200)

    async def test_concurrent_requests_share_one_unexpected_failure(self) -> None:
        session_id = self.sign_in_with_due_token()

        async def refresh(**_):
            await asyncio.sleep(0.05)  # still in flight while the others arrive
            raise RuntimeError("boom")

        eneo = self.use_eneo(refresh)

        with self.assertLogs("eneo_module_auth", level="ERROR"):
            responses = await asyncio.gather(*(self.get_flows(session_id) for _ in range(8)))

        self.assertEqual([r.status_code for r in responses], [200] * 8)
        self.assertEqual(len(eneo.refresh_calls), 1)
        self.assertEqual(self.auth._refreshes, {})

    async def test_concurrent_requests_share_one_failed_renewal(self) -> None:
        session_id = self.sign_in_with_due_token()

        async def refresh(**_):
            await asyncio.sleep(0.05)  # still in flight while the others arrive
            return httpx2.Response(503)

        eneo = self.use_eneo(refresh)

        responses = await asyncio.gather(
            *(self.get_flows(session_id) for _ in range(8))
        )

        self.assertEqual([r.status_code for r in responses], [200] * 8)
        self.assertEqual(len(eneo.refresh_calls), 1)
        self.assertEqual(
            {call["headers"]["Authorization"] for call in eneo.proxied},
            {"Bearer module-user-token"},
        )
        # Eneo just failed to answer, so the next request does not ask again yet.
        await self.get_flows(session_id)
        self.assertEqual(len(eneo.refresh_calls), 1)
        # Nothing outlives the refresh that it coordinated.
        self.assertEqual(self.auth._refreshes, {})


class HomePathTests(unittest.TestCase):
    """The home path is where a login lands when its own next does not fit, so it must fit itself, renewal and all."""

    @staticmethod
    def app_with(home_path: str) -> FastAPI:
        return create_app(
            Settings(
                eneo_backend_url="https://eneo.example.test",
                eneo_public_url="https://eneo.example.test",
                module_public_url="https://module.example.test",
                module_key="speech-to-text",
                eneo_api_key="test-key",
                session_secret="x" * 48,
                cookie_secure=False,
                home_path=home_path,
            ),
            http_client=FakeExchangeClient(),
        )

    def test_the_published_limit_is_256_bytes(self) -> None:
        # The number the configuration guide and the changelog give an author.
        self.assertEqual(MAX_HOME_PATH_BYTES, 256)

    def test_the_longest_home_path_allowed_fits_a_renewals_signed_state(self) -> None:
        # The proof of the limit, for the worst case: every field of the pending login filled (asserted below, so a
        # field added to it must be filled here too), counted as if nothing compressed (compression is used only when
        # shorter), and a home path of quotes, which JSON writes as two characters each (a backslash would too, but a
        # home path holds none).
        for kind, home in {
            "random ASCII": "/" + secrets.token_urlsafe(MAX_HOME_PATH_BYTES)[: MAX_HOME_PATH_BYTES - 1],
            "characters JSON doubles": "/" + '"' * (MAX_HOME_PATH_BYTES - 1),
        }.items():
            with self.subTest(kind):
                self.assertEqual(len(home.encode()), MAX_HOME_PATH_BYTES)
                module_auth = self.app_with(home).state.module_auth
                renewal = PendingLogin(
                    state=secrets.token_urlsafe(32), next=home, renew_user_id=str(uuid.uuid4()), renew_tenant_id=str(uuid.uuid4())
                )
                filled = {name for name, value in renewal.model_dump().items() if value}
                self.assertEqual(filled, set(PendingLogin.model_fields), "every field filled")

                with patch("itsdangerous.url_safe.zlib.compress", lambda data, *args, **kwargs: data + b"never shorter"):
                    signed = module_auth._signed_state(renewal)

                self.assertLessEqual(len(signed.encode()), MAX_STATE_COOKIE_BYTES)
                self.assertEqual(module_auth.state_serializer.loads(signed)["next"], home)

    def test_a_home_path_over_the_limit_stops_the_start_and_says_what_to_do(self) -> None:
        for home, size in (("/" + "a" * MAX_HOME_PATH_BYTES, MAX_HOME_PATH_BYTES + 1), ("/" + "\u754c" * 86, 259)):
            with self.subTest(size=size):
                with self.assertRaises(RuntimeError) as refused:
                    self.app_with(home)
                self.assertEqual(
                    str(refused.exception),
                    f"home_path is {size} bytes of UTF-8; at most {MAX_HOME_PATH_BYTES} fit a login's state cookie. "
                    "Choose a shorter one (load_settings(home_path=...) or Settings(home_path=...)).",
                )

    def test_a_home_path_with_a_control_character_stops_the_start(self) -> None:
        for home in ("/a\nb", "/a\tb", "/a\u2028b"):
            with self.subTest(home=home), self.assertRaisesRegex(RuntimeError, "^home_path holds a control character"):
                self.app_with(home)

    def test_a_home_path_that_is_no_path_of_the_module_stops_the_start_and_says_why(self) -> None:
        # The same rule as a login's next (module_path): what it would not take as a destination, it does not take here.
        for home, problem in (
            ("//elsewhere.example", "starts with //"),
            ("/a\\b", "holds a backslash"),
            ("flows", "does not start with /"),
            ("", "does not start with /"),
        ):
            with self.subTest(home=home):
                self.assertEqual(module_path(home, "/home"), "/home", "module_path refuses it as a next too")
                with self.assertRaises(RuntimeError) as refused:
                    self.app_with(home)
                said = str(refused.exception)
                self.assertTrue(said.startswith(f"home_path {problem}"), said)
                self.assertTrue(said.endswith("Choose another one (load_settings(home_path=...) or Settings(home_path=...))."), said)

    def test_a_home_path_that_cannot_be_written_as_utf_8_stops_the_start_and_says_why(self) -> None:
        with self.assertRaises(RuntimeError) as refused:
            self.app_with("/a\ud800b")
        self.assertEqual(
            str(refused.exception),
            "home_path cannot be written as UTF-8 (it holds a lone surrogate). "
            "Choose another one (load_settings(home_path=...) or Settings(home_path=...)).",
        )

    def test_an_ordinary_home_path_starts(self) -> None:
        for home in ("/", "/flows", "/" + "a" * (MAX_HOME_PATH_BYTES - 1)):
            with self.subTest(home=home[:20]):
                self.app_with(home)


if __name__ == "__main__":
    unittest.main()
