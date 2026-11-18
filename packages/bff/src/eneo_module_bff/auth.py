from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from typing import Annotated, Literal, NamedTuple
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

import httpx2
from fastapi import (
    APIRouter,
    Cookie,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocketException,
    status,
)
from fastapi.requests import HTTPConnection
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, ValidationError, field_validator

from .settings import Settings, canonical_origin, has_control_character
from .upstream import SMALL_ANSWER

logger = logging.getLogger("eneo_module_auth")

SESSION_COOKIE = "eneo_module_session"
# Each login that has not returned has a cookie of its own, named after its state (state_cookie_name), so a second
# login (another tab, the session cover's sign-in) never ends the first. It binds the callback to the browser that
# started the login, for Settings.login_timeout_seconds (LOGIN_TIMEOUT_MINUTES), and its callback clears it. On
# /api/auth, so that a new login sees how many wait; it therefore goes with every /api/auth request, the status too.
STATE_COOKIE = "eneo_module_login_state"
STATE_COOKIE_PATH = "/api/auth"
# Logins that may wait at once: a new login drops the oldest past this. A cleanup target, not a limit: two logins
# started before either answer lands can leave one more, until the next start.
MAX_PENDING_LOGINS = 5
# The browser session cookie's upper bound is Settings.session_max_age_seconds
# (SESSION_MAX_AGE_MINUTES). The session also ends at Eneo's
# session ceiling (module_auth_max_session_hours); the shorter-lived module
# token is refreshed through Eneo until then.
CALLBACK_PATH = "/api/auth/callback"
# After Eneo fails to answer a token refresh, wait this long before asking
# again; the current, still valid token stays in use meanwhile.
REFRESH_RETRY_SECONDS = 10
# How long the whole check of a refused token at Eneo's session route may take (ModuleAuth.login_refused), the answer
# included; past it nothing is confirmed and the session stays.
SESSION_CHECK_SECONDS = 10.0
# The methods that change nothing. A WebSocket handshake is a GET too, but the socket it opens acts for the user, so it
# is checked like a write.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class ModuleUser(BaseModel):
    id: str
    email: str
    username: str | None = None


class ModuleTokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"]
    expires_in: int
    # Eneo's fixed session ceiling; refresh renews the token only until then.
    session_expires_at: datetime
    module_key: str
    tenant_id: str
    user: ModuleUser

    @field_validator("session_expires_at")
    @classmethod
    def _utc_when_naive(cls, value: datetime) -> datetime:
        # Without a time zone it is UTC; read as local time it would end the session hours early or late.
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class ModuleResourceSessionResponse(BaseModel):
    module_key: str
    tenant_id: str
    user: ModuleUser


class ModuleSession(BaseModel):
    access_token: str
    # When the current token expires; the store drops the session then,
    # because Eneo refuses to refresh an expired token.
    expires_at: int
    # Halfway through the token's lifetime, or a short while after Eneo
    # failed to answer: refresh from here on.
    refresh_at: int
    # Fixed end of the login: min(SESSION_MAX_AGE_MINUTES, Eneo's ceiling).
    session_expires_at: int
    module_key: str
    tenant_id: str
    user: ModuleUser

    def refresh_in(self) -> int | None:
        """Seconds until a request should refresh the token.

        None when a new token could not outlive the current one, because the
        current one already reaches the session end.
        """
        if self.expires_at >= self.session_expires_at:
            return None
        return max(0, math.ceil(self.refresh_at - time.time()))

    def refresh_due(self) -> bool:
        return self.refresh_in() == 0


class PendingLogin(BaseModel):
    state: str
    # Where the callback sends the browser: a path of this module, never elsewhere.
    next: str
    # A renewal before the session ends may only renew the same user in the same tenant.
    renew_user_id: str | None = None
    renew_tenant_id: str | None = None


def with_query(path: str, query: str) -> str:
    """``path`` with ``query`` added, before any fragment so that the page still reads it."""
    parts = urlsplit(path)
    return urlunsplit(parts._replace(query=f"{parts.query}&{query}" if parts.query else query))


def state_cookie_name(state: str) -> str:
    """The cookie that holds this login's state; a digest, so the name is a valid cookie name whatever the query held."""
    return f"{STATE_COOKIE}_{hashlib.sha256(state.encode()).hexdigest()[:24]}"


# Only a name state_cookie_name gives: a cookie set under the prefix by anyone else (a site on the parent domain) is no
# login of this module's, and its name may be one the response could not even delete.
_STATE_COOKIE_NAME = re.compile(rf"{STATE_COOKIE}_[0-9a-f]{{24}}")


# The state cookie carries ``next``; a long one makes a cookie that browsers drop, and the login fails.
MAX_NEXT_LENGTH = 512
# The largest signed state a login keeps, in bytes; a next that would make it larger is the home path. Up to five waiting
# logins (six for a moment) go with every /api/auth request, and this keeps their Cookie header under a proxy's limit
# (ingress-nginx: 8 KB) whatever their next: past it, the proxy would refuse every login until they expire.
MAX_STATE_COOKIE_BYTES = 1024


def module_path(value: str | None, home_path: str) -> str:
    """``value`` when it is a short path on the module's own origin, else ``home_path`` (Settings.home_path).

    No control character, whatever it is: a browser (and urlsplit) removes a tab, CR or LF from a URL before it reads
    it, so ``/<tab>/host`` would be ``//host``, another origin, once a query is added to it.
    """
    if (
        value
        and len(value) <= MAX_NEXT_LENGTH
        and value.startswith("/")
        and not value.startswith("//")
        and "\\" not in value
        and not has_control_character(value)
    ):
        return value
    return home_path


# Expired sessions are swept at most this often. get() refuses an expired id itself, so a sweep only frees the memory.
PRUNE_INTERVAL_SECONDS = 30


class SignedUrl(NamedTuple):
    """A signed URL Eneo minted for one file of one session, until ``expires_at``."""

    url: str
    expires_at: float


class ModuleSessionStore:
    """Process-local opaque sessions for the single-process module image.

    The browser receives only a random identifier. Any Eneo user token remains
    in backend memory and logout removes the session immediately. A shared
    store is required before running more than one backend replica.

    The signed URLs minted for a session's files are kept here too, by session
    and mint path: each is a bearer URL to a file, so it must not outlive the
    session, however the session ends.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, ModuleSession] = {}
        self._signed_urls: dict[str, dict[str, SignedUrl]] = {}
        self._next_prune = 0.0  # on the monotonic clock
        self._lock = threading.Lock()

    def create(self, session: ModuleSession) -> str:
        session_id = secrets.token_urlsafe(32)
        with self._lock:
            self._prune_locked()
            self._sessions[session_id] = session
        return session_id

    def get(self, session_id: str | None) -> ModuleSession | None:
        if session_id is None:
            return None
        with self._lock:
            self._prune_locked()
            session = self._sessions.get(session_id)
            if session is None or session.expires_at <= time.time():
                # An id that is not live: one session at most, found by key, never by a scan.
                self._sessions.pop(session_id, None)
                self._signed_urls.pop(session_id, None)
                return None
            return session

    def replace(self, session_id: str, session: ModuleSession) -> None:
        # Only a live session: a logout during a token refresh stays a logout.
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id] = session

    def delete_if_token(self, session_id: str, access_token: str) -> bool:
        """Delete the session, and its signed URLs, if it still holds ``access_token``, in one step.

        True when the session is gone now, ended here or before (by a call beside this one, a logout, a new login or
        its expiry); False when it holds another token, renewed meanwhile, and it stays.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None and session.access_token != access_token:
                return False
            self._sessions.pop(session_id, None)
            self._signed_urls.pop(session_id, None)
            return True

    def delete(self, session_id: str | None) -> None:
        if session_id is None:
            return
        with self._lock:
            self._sessions.pop(session_id, None)
            self._signed_urls.pop(session_id, None)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()
            self._signed_urls.clear()

    def signed_url(self, session_id: str, mint_path: str) -> SignedUrl | None:
        with self._lock:
            return self._signed_urls.get(session_id, {}).get(mint_path)

    def remember_signed_url(self, session_id: str, mint_path: str, entry: SignedUrl) -> None:
        # Only for a live session: a logout can arrive while Eneo is still answering, and the entry would be
        # one that nothing removes.
        with self._lock:
            if session_id not in self._sessions:
                return
            urls = self._signed_urls.setdefault(session_id, {})
            now = time.time()
            for path in [path for path, known in urls.items() if known.expires_at <= now]:
                del urls[path]
            urls[mint_path] = entry

    def forget_signed_url(self, session_id: str, mint_path: str) -> None:
        with self._lock:
            urls = self._signed_urls.get(session_id)
            if urls is not None:
                urls.pop(mint_path, None)
                if not urls:
                    del self._signed_urls[session_id]

    def _prune_locked(self) -> None:
        """Drop the expired sessions and their signed URLs, at most once per PRUNE_INTERVAL_SECONDS.

        Each call used to scan every session on the event loop (340 us at 10 000), and a garbage cookie paid for it
        too. Nothing depends on this sweep for correctness: get() refuses an expired session by itself.
        """
        monotonic = time.monotonic()
        if monotonic < self._next_prune:
            return
        self._next_prune = monotonic + PRUNE_INTERVAL_SECONDS
        now = time.time()
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if session.expires_at <= now
        ]
        for session_id in expired:
            del self._sessions[session_id]
            self._signed_urls.pop(session_id, None)


def eneo_is_unavailable(status_code: int) -> bool:
    """Eneo could not answer right now, as opposed to refusing."""
    return status_code in {408, 429} or status_code >= 500


def refuses_the_login(answer: httpx2.Response) -> bool:
    """Eneo's answer says that the user's token is not valid any more: 401, and the code ``authentication_error`` at the
    top of its JSON body, the string code Eneo documents for its clients to branch on.

    It is a revoked token (a changed password, "log out everywhere"), an expired one, or one whose user is gone; but a
    route of Eneo's that takes no module tokens answers the same for a valid one. So it is not proof that the login is
    over: ``ModuleAuth.login_refused`` asks Eneo's session route first. Nothing else is this: not ``invalid_api_key``
    (the module's key, not the user's), no 403, no other 401 code (a step-up asks for more of the same login), and no
    body without the code at its top. The number ``eneo_error_code`` is not read: 9005 is ``invalid_api_key``'s too.
    """
    if answer.status_code != 401:
        return False
    try:
        body = json.loads(answer.content)
    except (ValueError, RecursionError):
        # RecursionError: JSON nested deeper than the parser goes is a body that cannot be read, not a 500.
        return False
    return isinstance(body, dict) and body.get("code") == "authentication_error"


def session_ended() -> HTTPException:
    """The kit's answer when the browser's session is gone: 401 and ``X-Auth-Required: session``, which the page reads as
    its login's end and answers with a new login in place. No body of Eneo's goes with it."""
    return HTTPException(status_code=401, detail="Not authenticated", headers={"X-Auth-Required": "session"})


def _refusal(connection: HTTPConnection, error: HTTPException) -> Exception:
    """``error`` for an HTTP request; a WebSocket handshake is closed unaccepted."""
    if connection.scope["type"] == "websocket":
        return WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION, reason=str(error.detail)
        )
    return error


class ModuleAuth:
    def __init__(
        self,
        *,
        settings: Settings,
        http_client: httpx2.AsyncClient,
    ) -> None:
        self.settings = settings
        self.http_client = http_client
        self.state_serializer = URLSafeTimedSerializer(
            settings.session_secret,
            salt="eneo-module-login-state",
        )
        self.sessions = ModuleSessionStore()
        # Token refreshes in flight, by session id; an entry lives only while
        # its refresh runs.
        self._refreshes: dict[str, asyncio.Task[None]] = {}
        self.router = APIRouter()
        self.router.add_api_route("/login", self.login, methods=["GET"])
        self.router.add_api_route("/callback", self.callback, methods=["GET"])
        self.router.add_api_route("/logout", self.logout, methods=["POST"])
        self.router.add_api_route("/status", self.status, methods=["GET"])

    @property
    def callback_url(self) -> str:
        return f"{self.settings.module_public_url}{CALLBACK_PATH}"

    @property
    def _session_url(self) -> str:
        """Eneo's session route: who a token is, with the module's key beside it, as every resource call checks both."""
        return f"{self.settings.eneo_backend_url}/api/v1/module-auth/{quote(self.settings.module_key, safe='')}/session/"

    async def login(
        self,
        request: Request,
        next_path: Annotated[str | None, Query(alias="next")] = None,
        renew: Annotated[bool, Query()] = False,
        session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    ) -> RedirectResponse:
        state = secrets.token_urlsafe(32)
        # A login in a separate window (before the session ends) returns to a page that closes it, and is
        # bound to the user signed in now, so the page's work never passes to someone else.
        current = self.sessions.get(session_id) if renew else None
        if renew and current is None:
            # Nobody left to bind to: refused, not an ordinary login that anyone could finish under this page.
            refused = RedirectResponse(
                url=with_query(module_path(next_path, self.settings.home_path), "fel=utgangen"), status_code=303
            )
            refused.headers["Cache-Control"] = "no-store"
            return refused
        login = PendingLogin(
            state=state,
            next=module_path(next_path, self.settings.home_path),
            renew_user_id=current.user.id if current is not None else None,
            renew_tenant_id=current.tenant_id if current is not None else None,
        )
        pending = self.state_serializer.dumps(login.model_dump())
        if len(pending.encode()) > MAX_STATE_COOKIE_BYTES:
            pending = self.state_serializer.dumps(login.model_copy(update={"next": self.settings.home_path}).model_dump())
        query = urlencode(
            {
                "module_key": self.settings.module_key,
                "redirect_uri": self.callback_url,
                "state": state,
            }
        )
        response = RedirectResponse(
            url=f"{self.settings.eneo_public_url}/module-login?{query}",
            status_code=303,
        )
        for oldest in self._pending_logins(request)[: -MAX_PENDING_LOGINS + 1 or None]:
            self._delete_state_cookie(response, oldest)
        response.set_cookie(
            key=state_cookie_name(state),
            value=pending,
            httponly=True,
            secure=self.settings.cookie_secure,
            samesite="lax",
            max_age=self.settings.login_timeout_seconds,
            path=STATE_COOKIE_PATH,
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    def _pending_logins(self, request: Request) -> list[str]:
        """The browser's waiting logins' cookie names, oldest first; one that cannot be read counts as the oldest."""

        def started(name: str) -> float:
            try:
                return self.state_serializer.loads(request.cookies[name], return_timestamp=True)[1].timestamp()
            except (BadSignature, ValueError):
                return 0

        return sorted((name for name in request.cookies if _STATE_COOKIE_NAME.fullmatch(name)), key=started)

    async def callback(
        self,
        request: Request,
        ticket: Annotated[str | None, Query()] = None,
        state: Annotated[str | None, Query()] = None,
        held_session_id: Annotated[
            str | None,
            Cookie(alias=SESSION_COOKIE),
        ] = None,
    ) -> RedirectResponse:
        # Only this login's own cookie: another login's state, however valid, never admits this callback.
        cookie_name = state_cookie_name(state) if state is not None else None
        pending = self._load_pending_login(request.cookies.get(cookie_name) if cookie_name else None)
        if (
            ticket is None
            or state is None
            or pending is None
            or not secrets.compare_digest(state.encode(), pending.state.encode())
        ):
            return self._auth_error(cookie_name, "invalid_state")

        try:
            upstream = await self.http_client.post(
                f"{self.settings.eneo_backend_url}/api/v1/module-auth/token/",
                headers=self._eneo_headers(),
                json={"ticket": ticket},
                timeout=httpx2.Timeout(10.0),
                extensions=SMALL_ANSWER,
            )
        except httpx2.RequestError as error:
            # The kind of error, never its text, here and below: httpx2's quotes a header it could not send, and a
            # validation error the answer it refused. Either can hold a token.
            logger.error("Module ticket exchange could not reach Eneo (%s)", type(error).__name__)
            return self._auth_error(cookie_name, "exchange_unavailable")

        if upstream.status_code != 200:
            logger.warning(
                "Module ticket exchange failed with status %s",
                upstream.status_code,
            )
            return self._auth_error(cookie_name, "exchange_failed")

        try:
            token = ModuleTokenResponse.model_validate(upstream.json())
        except (ValueError, ValidationError):
            logger.error("Module ticket exchange returned an invalid response")
            return self._auth_error(cookie_name, "exchange_invalid")

        now = int(time.time())
        session_expires_at = min(
            now + self.settings.session_max_age_seconds,
            int(token.session_expires_at.timestamp()),
        )
        if (
            token.module_key != self.settings.module_key
            or token.expires_in <= 0
            or session_expires_at <= now
        ):
            logger.error("Module ticket exchange returned the wrong module or expiry")
            return self._auth_error(cookie_name, "exchange_invalid")

        try:
            validation = await self.http_client.get(
                self._session_url,
                headers=self._eneo_headers(token.access_token),
                timeout=httpx2.Timeout(10.0),
                extensions=SMALL_ANSWER,
            )
        except httpx2.RequestError as error:
            logger.error("Module session validation could not reach Eneo (%s)", type(error).__name__)
            return self._auth_error(cookie_name, "validation_unavailable")

        if validation.status_code != 200:
            logger.warning(
                "Module session validation failed with status %s",
                validation.status_code,
            )
            return self._auth_error(cookie_name, "validation_failed")
        try:
            validated = ModuleResourceSessionResponse.model_validate(validation.json())
        except (ValueError, ValidationError):
            logger.error("Module session validation returned an invalid response")
            return self._auth_error(cookie_name, "validation_invalid")
        if (
            validated.module_key != token.module_key
            or validated.tenant_id != token.tenant_id
            or validated.user.id != token.user.id
        ):
            logger.error("Module session validation returned a different identity")
            return self._auth_error(cookie_name, "validation_invalid")

        if pending.renew_user_id is not None and (
            token.user.id != pending.renew_user_id or token.tenant_id != pending.renew_tenant_id
        ):
            logger.warning("A session renewal signed in a different user; the session is kept")
            response = RedirectResponse(url=with_query(pending.next, "fel=annan-anvandare"), status_code=303)
            self._delete_state_cookie(response, cookie_name)
            self._secure_callback_response(response)
            return response

        session = ModuleSession(
            access_token=token.access_token,
            expires_at=min(now + token.expires_in, session_expires_at),
            refresh_at=now + token.expires_in // 2,
            session_expires_at=session_expires_at,
            module_key=token.module_key,
            tenant_id=token.tenant_id,
            user=token.user,
        )
        response = RedirectResponse(url=pending.next, status_code=303)
        self._set_session_cookie(
            response, session=session, max_age=session_expires_at - now
        )
        # The new cookie replaces the browser's old one, so the old session ends with it: a login, or a
        # renewal by the same user, must not leave two sessions alive for one browser.
        self.sessions.delete(held_session_id)
        self._delete_state_cookie(response, cookie_name)
        self._secure_callback_response(response)
        return response

    async def logout(
        self,
        request: Request,
        response: Response,
        session_id: Annotated[
            str | None,
            Cookie(alias=SESSION_COOKIE),
        ] = None,
    ) -> dict[str, bool]:
        self.require_same_origin(request)
        self.sessions.delete(session_id)
        response.delete_cookie(
            SESSION_COOKIE,
            path="/",
            secure=self.settings.cookie_secure,
            httponly=True,
            samesite="lax",
        )
        response.headers["Cache-Control"] = "no-store"
        return {"ok": True}

    async def status(
        self,
        response: Response,
        session_id: Annotated[
            str | None,
            Cookie(alias=SESSION_COOKIE),
        ] = None,
    ) -> dict[str, object]:
        response.headers["Cache-Control"] = "no-store"
        session = await self._live_session(session_id)
        if session is None:
            return {"authenticated": False, "user": None}
        status: dict[str, object] = {
            "authenticated": True,
            "user": session.user.model_dump(exclude_none=True),
        }
        # The login's fixed end (Eneo's ceiling or the module's own), so the page can warn before it.
        status["session_ends_in"] = max(0, session.session_expires_at - int(time.time()))
        refresh_in = session.refresh_in()
        if refresh_in is not None:
            # The page asks again then, so even a session that sends no
            # other request (a recording) is refreshed before it expires.
            status["refresh_in"] = refresh_in
        return status

    async def require_session(
        self,
        connection: HTTPConnection,
        session_id: Annotated[
            str | None,
            Cookie(alias=SESSION_COOKIE),
        ] = None,
    ) -> ModuleSession:
        session = await self._live_session(session_id)
        if session is None:
            raise _refusal(connection, session_ended())
        # What the request was admitted under: the token it sends to Eneo, and the session that a refusal of it may end.
        connection.state.module_session = session
        connection.state.module_session_id = session_id
        return session

    async def raise_if_session_ended(self, connection: HTTPConnection, answer: httpx2.Response) -> None:
        """``session_ended()`` (a socket: closed with 1008) when Eneo's ``answer`` to a call made with this request's
        token means that its login is over, the session then gone (``login_refused``); else nothing, and the caller
        answers Eneo's ``answer`` as it would anyway.

        The answer must have been read: a streamed one (``stream=True``) is a RuntimeError, whatever its status, so that
        a call that would let a refusal pass unseen fails the first time it runs.
        """
        try:
            answer.content
        except httpx2.ResponseNotRead:
            raise RuntimeError(
                "raise_if_session_ended needs Eneo's answer read: call `await answer.aread()` first, "
                "or make the call without stream=True"
            ) from None
        if await self.login_refused(connection, answer):
            raise _refusal(connection, session_ended())

    async def login_refused(self, connection: HTTPConnection, answer: httpx2.Response) -> bool:
        """Whether Eneo's ``answer`` to a call made with this request's token means its login is over, the session
        then gone. False: Eneo's answer goes on as it is.

        The one rule for every call made with the user's token. A refusal that may end the login
        (``refuses_the_login``) ends it only when the session still holds the token that was refused and Eneo's own
        session route refuses that token too, asked once per refusal; anything else confirms nothing. A session that
        is gone already gets the answer without a check, as ``require_session`` would; one renewed since the call went
        out is not about this refusal, and the page counts a renewal as the same login, so Eneo's answer goes on. The
        refresh keeps a rule of its own: it asks whether the session can go on, and ends it at any refusal.
        """
        if not refuses_the_login(answer):
            return False
        sent = self.session_from_request(connection)
        session_id = connection.state.module_session_id
        held = self.sessions.get(session_id)
        if held is None:
            return True
        if held.access_token != sent.access_token:
            return False
        if not await self._eneo_confirms_the_end(sent):
            # A refusal of the same token at the same time may have ended the session while this check waited.
            if self.sessions.get(session_id) is None:
                return True
            logger.warning("Eneo refused a session's token, and its session route did not confirm it: the session stays")
            return False
        ended = self.sessions.delete_if_token(session_id, sent.access_token)
        if ended:
            logger.info("Eneo refused a session's token, and its session route confirmed it: the session has ended")
        return ended

    async def _eneo_confirms_the_end(self, session: ModuleSession) -> bool:
        """Eneo's session route refuses ``session``'s token as the call was refused. Bounded in time, the answer
        included, and in size; an answer of any other kind, none in time or none at all, confirms nothing."""
        try:
            async with asyncio.timeout(SESSION_CHECK_SECONDS):
                answer = await self.http_client.get(
                    self._session_url,
                    headers=self._eneo_headers(session.access_token),
                    timeout=httpx2.Timeout(SESSION_CHECK_SECONDS),
                    extensions=SMALL_ANSWER,
                )
        except (httpx2.RequestError, TimeoutError):
            return False
        return refuses_the_login(answer)

    async def _live_session(self, session_id: str | None) -> ModuleSession | None:
        """The caller's session, with its module token refreshed once due."""
        if session_id is None:
            return None
        session = self.sessions.get(session_id)
        if session is None:
            return None
        if session.refresh_due():
            # One refresh per session: concurrent requests wait for the same
            # one, and a request that goes away does not cancel it for them.
            refresh = self._refreshes.get(session_id)
            if refresh is None:
                refresh = asyncio.create_task(self._refresh(session_id, session))
                self._refreshes[session_id] = refresh
            await asyncio.shield(refresh)
            # Refreshed, retried later or ended meanwhile, and the wait may have
            # outlasted the token: only what the store holds now is valid.
            session = self.sessions.get(session_id)
        return session

    async def _refresh(self, session_id: str, session: ModuleSession) -> None:
        try:
            refreshed = await self._refresh_token(session)
            if refreshed is None:
                self.sessions.delete(session_id)
            else:
                self.sessions.replace(session_id, refreshed)
        except Exception as error:
            # Not an answer from Eneo, so not a reason to end the session: keep the token, which is still valid,
            # and ask again shortly, as when Eneo cannot answer. Left alone, the error would reach every request
            # of the session as a 500. (Not BaseException: a cancelled refresh stays cancelled.) Its kind, not its
            # text, which can quote the token.
            logger.error("Module token refresh failed unexpectedly (%s)", type(error).__name__)
            self.sessions.replace(session_id, self._retry_later(session))
        finally:
            self._refreshes.pop(session_id, None)

    async def _refresh_token(self, session: ModuleSession) -> ModuleSession | None:
        """Renew the token; None when Eneo refuses, so the user signs in again.

        When Eneo cannot answer right now the session keeps its token, which
        is still valid, and asks again after REFRESH_RETRY_SECONDS.
        """
        try:
            upstream = await self.http_client.post(
                (
                    f"{self.settings.eneo_backend_url}/api/v1/module-auth/"
                    f"{quote(self.settings.module_key, safe='')}/token/refresh/"
                ),
                headers=self._eneo_headers(session.access_token),
                timeout=httpx2.Timeout(10.0),
                extensions=SMALL_ANSWER,
            )
        except httpx2.RequestError as error:
            logger.warning("Module token refresh could not reach Eneo (%s)", type(error).__name__)
            return self._retry_later(session)
        if eneo_is_unavailable(upstream.status_code):
            logger.warning(
                "Module token refresh failed with status %s", upstream.status_code
            )
            return self._retry_later(session)
        if upstream.status_code != 200:
            logger.warning(
                "Eneo refused the module token refresh with status %s",
                upstream.status_code,
            )
            return None
        try:
            token = ModuleTokenResponse.model_validate(upstream.json())
        except (ValueError, ValidationError):
            logger.error("Module token refresh returned an invalid response")
            return None
        if (
            token.module_key != session.module_key
            or token.tenant_id != session.tenant_id
            or token.user.id != session.user.id
            or token.expires_in <= 0
        ):
            logger.error("Module token refresh returned a different identity or expiry")
            return None
        now = int(time.time())
        return session.model_copy(
            update={
                "access_token": token.access_token,
                "expires_at": min(now + token.expires_in, session.session_expires_at),
                "refresh_at": now + token.expires_in // 2,
            }
        )

    @staticmethod
    def _retry_later(session: ModuleSession) -> ModuleSession:
        return session.model_copy(
            update={"refresh_at": int(time.time()) + REFRESH_RETRY_SECONDS}
        )

    def require_same_origin(self, connection: HTTPConnection) -> None:
        if isinstance(connection, Request) and connection.method in SAFE_METHODS:
            return
        origin = canonical_origin(connection.headers.get("origin") or "", origin_only=True)
        if origin != self.settings.module_origin:
            raise _refusal(
                connection, HTTPException(status_code=403, detail="Invalid request origin")
            )

    def require_expected_user(self, connection: HTTPConnection, session: ModuleSession) -> None:
        """409 ``user_changed`` when the page that sent the request is not the session's user's.

        A browser has one cookie for every tab: a login in one tab replaces the session under a page open in another,
        which would go on writing as the new person. The page names its user in ``X-Expected-User`` (an id, not a
        secret). A write must name the session's user; a read may name nobody (an ``<img src>`` or a navigation sends
        no header of the page's), but one it names must be the session's.
        """
        expected = connection.headers.get("x-expected-user")
        write = not (isinstance(connection, Request) and connection.method in SAFE_METHODS)
        if expected != session.user.id and (expected is not None or write):
            logger.info("A request was refused: its page names another user than the session's, or none")
            raise _refusal(connection, HTTPException(status_code=409, detail="user_changed"))

    @staticmethod
    def session_from_request(connection: HTTPConnection) -> ModuleSession:
        session = getattr(connection.state, "module_session", None)
        if not isinstance(session, ModuleSession):
            raise RuntimeError("Module session dependency did not run")
        return session

    def _eneo_headers(self, access_token: str | None = None) -> dict[str, str]:
        """Eneo's credentials: the module's key, and a user's token once there is one."""
        headers = {self.settings.eneo_api_key_header_name: self.settings.eneo_api_key}
        if access_token is not None:
            headers["Authorization"] = f"Bearer {access_token}"
        return headers

    def upstream_auth_headers(self, connection: HTTPConnection) -> dict[str, str]:
        return self._eneo_headers(self.session_from_request(connection).access_token)

    def _set_session_cookie(
        self,
        response: Response,
        *,
        session: ModuleSession,
        max_age: int,
    ) -> None:
        session_id = self.sessions.create(session)
        response.set_cookie(
            key=SESSION_COOKIE,
            value=session_id,
            httponly=True,
            secure=self.settings.cookie_secure,
            samesite="lax",
            max_age=max_age,
            path="/",
        )

    def _load_pending_login(self, cookie: str | None) -> PendingLogin | None:
        if cookie is None:
            return None
        try:
            payload = self.state_serializer.loads(cookie, max_age=self.settings.login_timeout_seconds)
            return PendingLogin.model_validate(payload)
        except (BadSignature, SignatureExpired, ValidationError):
            return None

    def _auth_error(self, cookie_name: str | None, code: str) -> RedirectResponse:
        response = RedirectResponse(
            url=f"/?{urlencode({'auth_error': code})}",
            status_code=303,
        )
        if cookie_name is not None:
            self._delete_state_cookie(response, cookie_name)
        self._secure_callback_response(response)
        return response

    def _delete_state_cookie(self, response: Response, name: str) -> None:
        response.delete_cookie(
            name,
            path=STATE_COOKIE_PATH,
            secure=self.settings.cookie_secure,
            httponly=True,
            samesite="lax",
        )

    @staticmethod
    def _secure_callback_response(response: Response) -> None:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
