import asyncio
import itertools
import os
import re
import secrets
import time
import timeit
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import httpx2
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from eneo_module_bff.app import create_app
from eneo_module_bff.auth import (
    ModuleAuth,
    ModuleSession,
    ModuleSessionStore,
    ModuleUser,
    SESSION_COOKIE,
    SignedUrl,
    STATE_COOKIE,
    with_query,
)
from eneo_module_bff.deps import require_session, upstream_auth_headers
from eneo_module_bff.settings import Settings

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
        self.assertIn("eneo_module_login_state", response.cookies)
        return query["state"][0], location

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

    def test_a_next_above_512_characters_falls_back_to_the_home_path(self) -> None:
        # 6 000 characters make a state cookie of 8 KB, which browsers drop: the login would fail as invalid_state.
        for length, lands_on_next in ((512, True), (513, False), (6000, False)):
            with self.subTest(length=length):
                # Random, because the signed state is compressed: a repeated character would hide the size.
                long_next = "/" + secrets.token_urlsafe(length)[: length - 1]
                login = self.client.get("/api/auth/login", params={"next": long_next})
                state_cookie = next(h for h in login.headers.get_list("set-cookie") if h.startswith(f"{STATE_COOKIE}="))
                self.assertLess(len(state_cookie), 4096)
                state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]

                callback = self.client.get("/api/auth/callback", params={"ticket": "one-time-ticket", "state": state})

                self.assertEqual(callback.headers["location"], long_next if lands_on_next else "/flows")

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
                self.assertNotIn(STATE_COOKIE, response.cookies)
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

        response = await asyncio.wait_for(self.get_flows(other), timeout=2)

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


if __name__ == "__main__":
    unittest.main()
