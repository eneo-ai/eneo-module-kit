"""A stand-in for Eneo's side of the module contract, for developing and testing a module without Eneo.
Development and tests only; never shipped in the image.

    python3 stub-eneo/server.py [port]            # default 8411 (STUB_HOST, default 127.0.0.1)

It answers what a module's BFF asks of Eneo (docs/module-contract.md):
  GET  /module-login?module_key&redirect_uri&state    sends the browser back to redirect_uri with a one-time ticket
                                                      and the unchanged state (the stub signs everyone in as Erik Lund)
  POST /api/v1/module-auth/token/                     the ticket, once, for a module-user token; needs the service key
  GET  /api/v1/module-auth/{module_key}/session/      who the token is; needs both credentials
  POST /api/v1/module-auth/{module_key}/token/refresh/  a new token; needs both credentials
  GET  /api/v1/flows/                                 two published flows; needs both credentials
A call without both credentials (the service key in X-API-Key and the module-user token as a bearer token) is a 401.

For tests, unauthenticated control routes. Each holds for the caller's scope: the `stub_scope` cookie, which a browser
test's context sends to these routes and to /module-login (template/web/tests/e2e/fixtures.ts), so that tests running at
once do not change each other's answers. A login and its tokens keep the scope of the browser that signed in. Without the
cookie (curl, a browser by hand) the scope is the one of everyone else without it.
  POST /__stub/end-session                            the scope's tokens are refused from now on, as when Eneo ends the login: the
                                                      module's session ends at its next refresh (with token_seconds=4, within a few
                                                      seconds)
  POST /__stub/session?ends_in=S&token_seconds=T      for the scope's logins made after this call: the session ends S seconds after the
                                                      login (Eneo's ceiling; a refresh keeps it) and a token lives T seconds (the module
                                                      refreshes at half). Defaults 28800 and 900; `reset` as a value restores them
  POST /__stub/login-as?user=erik|sara                who the scope's logins made after this call are (default erik: Erik Lund), to show
                                                      a renewal that signs in someone else
  POST /__stub/flows?mode=normal|empty|error          what the flow list answers the scope's tokens (two flows, none, or a 500)
"""

import json
import os
import secrets
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlencode, urlparse

MODULE_KEY = os.environ.get("STUB_MODULE_KEY", "eneo-module")
API_KEY = os.environ.get("STUB_ENEO_API_KEY", "stub-service-key")
USERS = {
    "erik": {"id": "user-1", "email": "erik.lund@example.test", "username": "Erik Lund"},
    "sara": {"id": "user-2", "email": "sara.holm@example.test", "username": "Sara Holm"},
}
TENANT = "tenant-1"
TOKEN_SECONDS = 900
SESSION_SECONDS = 8 * 60 * 60

FLOWS = [
    {"id": "flow-1", "name": "Nämndmöte till rapport", "description": "Transkriberar mötet och skapar en rapport.", "published_version": 3,
     "is_published": True, "space_id": "space-1", "space_name": "Kommunledningskontoret"},
    {"id": "flow-2", "name": "Intervju till sammanfattning", "description": "Sammanfattar en intervju med citat och teman.", "published_version": 7,
     "is_published": True, "space_id": "space-1", "space_name": "Kommunledningskontoret"},
]


SCOPE_COOKIE = "stub_scope"


class Controls:
    """What the test controls set for one scope: who its next logins are, how long they last, and what its flow list answers."""

    def __init__(self) -> None:
        self.user = "erik"
        self.flows_mode = "normal"
        self.session_seconds = SESSION_SECONDS
        self.token_seconds = TOKEN_SECONDS


# A token's end of session, its user and its scope.
Login = tuple[datetime, dict[str, str], str]


class State:
    """What the stub remembers: tickets not yet exchanged and the tokens it has given, each with its scope, and the controls of
    each scope."""

    def __init__(self) -> None:
        self.tickets: dict[str, tuple[float, str]] = {}
        self.tokens: dict[str, Login] = {}
        self.scopes: defaultdict[str, Controls] = defaultdict(Controls)

    def new_token(self, scope: str, previous: Login | None = None) -> dict[str, object]:
        """A token for a new login in ``scope`` (the session ends ``session_seconds`` from now, for its current ``user``), or
        for a refresh (``previous``: the same end, the same user, the same scope)."""
        controls = self.scopes[scope]
        token = secrets.token_urlsafe(24)
        login = previous or (datetime.now(timezone.utc) + timedelta(seconds=controls.session_seconds), USERS[controls.user], scope)
        self.tokens[token] = login
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": controls.token_seconds,
            "session_expires_at": login[0].isoformat(),
            "module_key": MODULE_KEY,
            "tenant_id": TENANT,
            "user": login[1],
        }


STATE = State()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # quiet: a ticket is in the callback URL
        pass

    def send_json(self, status: int, body: object) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def refuse(self, why: str) -> None:
        self.send_json(401, {"detail": why})

    def has_service_key(self) -> bool:
        return secrets.compare_digest(self.headers.get("X-API-Key", ""), API_KEY)

    def bearer(self) -> str | None:
        header = self.headers.get("Authorization", "")
        return header[7:] if header.startswith("Bearer ") else None

    def login(self) -> Login | None:
        """The login of the bearer token, when the call also has the service key: both credentials, or None."""
        return STATE.tokens.get(self.bearer() or "") if self.has_service_key() else None

    def scope(self) -> str:
        """The caller's scope: its stub_scope cookie, or none."""
        for pair in self.headers.get("Cookie", "").split(";"):
            name, _, value = pair.strip().partition("=")
            if name == SCOPE_COOKIE:
                return value
        return ""

    def body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return {}

    def do_GET(self) -> None:
        url = urlparse(self.path)
        path = url.path
        if path == "/health":
            return self.send_json(200, {"ok": True})
        if path == "/module-login":
            query = {key: values[0] for key, values in parse_qs(url.query).items()}
            if query.get("module_key") != MODULE_KEY or not query.get("redirect_uri") or not query.get("state"):
                return self.send_json(400, {"detail": "module_key, redirect_uri and state are required, and the module key must be this module's"})
            ticket = secrets.token_urlsafe(24)
            STATE.tickets[ticket] = (time.time() + 60, self.scope())
            self.send_response(303)
            self.send_header("Location", f"{query['redirect_uri']}?{urlencode({'ticket': ticket, 'state': query['state']})}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == f"/api/v1/module-auth/{quote(MODULE_KEY)}/session/":
            if (login := self.login()) is None:
                return self.refuse("both the service key and the module-user token are required")
            return self.send_json(200, {"module_key": MODULE_KEY, "tenant_id": TENANT, "user": login[1]})
        if path == "/api/v1/flows/":
            if (login := self.login()) is None:
                return self.refuse("both the service key and the module-user token are required")
            mode = STATE.scopes[login[2]].flows_mode
            if mode == "error":
                return self.send_json(500, {"detail": "The stub was told to fail."})
            items = [] if mode == "empty" else FLOWS
            return self.send_json(200, {"has_more": False, "count": len(items), "items": items})
        self.send_json(404, {"detail": f"stub: {path}"})

    def do_POST(self) -> None:
        url = urlparse(self.path)
        path = url.path
        if path == "/api/v1/module-auth/token/":
            if not self.has_service_key():
                return self.refuse("the service key is required")
            ticket = self.body().get("ticket")
            expires, scope = STATE.tickets.pop(ticket, (0, "")) if isinstance(ticket, str) else (0, "")
            if expires < time.time():
                return self.send_json(400, {"detail": "The ticket is unknown, used or expired."})
            return self.send_json(200, STATE.new_token(scope))
        if path == f"/api/v1/module-auth/{quote(MODULE_KEY)}/token/refresh/":
            if (login := self.login()) is None:
                return self.refuse("both the service key and the module-user token are required")
            return self.send_json(200, STATE.new_token(login[2], login))
        if path == "/__stub/end-session":
            scope = self.scope()
            # A copy to walk: another test's login may add a token meanwhile.
            for token, login in list(STATE.tokens.items()):
                if login[2] == scope:
                    STATE.tokens.pop(token, None)
            return self.send_json(200, {"ok": True})
        controls = STATE.scopes[self.scope()]
        if path == "/__stub/session":
            query = parse_qs(url.query)
            try:
                for name, attribute, default in (("ends_in", "session_seconds", SESSION_SECONDS), ("token_seconds", "token_seconds", TOKEN_SECONDS)):
                    if name in query:
                        value = default if query[name][0] == "reset" else int(query[name][0])
                        if value < 1:
                            raise ValueError(name)
                        setattr(controls, attribute, value)
            except ValueError:
                return self.send_json(400, {"detail": "ends_in and token_seconds are whole seconds of at least 1, or reset"})
            return self.send_json(200, {"ok": True, "ends_in": controls.session_seconds, "token_seconds": controls.token_seconds})
        if path == "/__stub/login-as":
            user = parse_qs(url.query).get("user", [""])[0]
            if user not in USERS:
                return self.send_json(400, {"detail": "user is erik or sara"})
            controls.user = user
            return self.send_json(200, {"ok": True, "user": USERS[user]["username"]})
        if path == "/__stub/flows":
            mode = parse_qs(url.query).get("mode", ["normal"])[0]
            if mode not in {"normal", "empty", "error"}:
                return self.send_json(400, {"detail": "mode is normal, empty or error"})
            controls.flows_mode = mode
            return self.send_json(200, {"ok": True, "mode": mode})
        self.send_json(404, {"detail": f"stub: {path}"})


def serve(port: int = 8411, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("STUB_PORT", "8411"))
    host = os.environ.get("STUB_HOST", "127.0.0.1")
    print(f"Stub Eneo on http://{host}:{port} (module key {MODULE_KEY})", flush=True)
    serve(port, host).serve_forever()
