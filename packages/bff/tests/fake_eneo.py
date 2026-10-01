"""Eneo as a real ASGI app behind a real client, for the tests that look at what a second server receives.

``FakeEneo`` records each request as its server would see it (the path decoded once, as uvicorn does) and answers
with whatever the test says. ``Module`` is a module on the kit with a real ``httpx2`` client pointed at it, and
``browser()`` is a signed-in browser of that module.
"""

import time
from collections.abc import AsyncIterator, Callable
from typing import NamedTuple

import httpx2
from fastapi import APIRouter

from eneo_module_bff.app import create_app
from eneo_module_bff.auth import SESSION_COOKIE, ModuleSession, ModuleUser
from eneo_module_bff.proxy import ProxyRule
from eneo_module_bff.settings import Settings

ORIGIN = "http://module.example.test"


class Seen(NamedTuple):
    method: str
    path: str  # decoded once, like the path a server hands its app
    raw_path: bytes
    query: bytes
    headers: dict[str, str]
    body: bytes


class Answer:
    """What Eneo answers: a status, headers, and a body that is bytes or a lazy stream of them."""

    def __init__(self, status: int = 200, body: bytes | Callable[[], AsyncIterator[bytes]] = b'{"ok":true}', headers: list[tuple[str, str]] | None = None) -> None:
        self.status = status
        self.body = body
        self.headers = [("content-type", "application/json")] if headers is None else headers


class FakeEneo:
    def __init__(self, answer: Callable[[Seen], Answer] | Answer | None = None) -> None:
        self.seen: list[Seen] = []
        self.answer = answer or Answer()
        self.closed = 0  # answers whose body was not read to its end

    async def __call__(self, scope, receive, send) -> None:
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        headers = {name.decode().lower(): value.decode("latin-1") for name, value in scope["headers"]}
        seen = Seen(scope["method"], scope["path"], scope["raw_path"], scope["query_string"], headers, body)
        self.seen.append(seen)
        answer = self.answer(seen) if callable(self.answer) else self.answer
        await send({"type": "http.response.start", "status": answer.status, "headers": [(k.encode(), v.encode()) for k, v in answer.headers]})
        finished = False
        try:
            if callable(answer.body):
                async for chunk in answer.body():
                    await send({"type": "http.response.body", "body": chunk, "more_body": True})
            else:
                await send({"type": "http.response.body", "body": answer.body, "more_body": True})
            await send({"type": "http.response.body", "body": b""})
            finished = True
        finally:
            if not finished:
                self.closed += 1


def session(user_id: str = "u") -> ModuleSession:
    now = int(time.time())
    return ModuleSession(
        access_token=f"token-of-{user_id}", expires_at=now + 600, refresh_at=now + 300, session_expires_at=now + 3600,
        module_key="fake", tenant_id="t", user=ModuleUser(id=user_id, email=f"{user_id}@example.test"),
    )


class Module:
    """A module on the kit whose Eneo is ``eneo``; ``test`` closes what it opens."""

    def __init__(self, test, eneo: FakeEneo, *, routers: tuple[APIRouter, ...] = (), proxy_rules: tuple[ProxyRule, ...] = (), **overrides) -> None:
        self.test = test
        self.eneo = eneo
        self.settings = Settings(
            eneo_backend_url="http://eneo.test", eneo_public_url="http://eneo.example", module_public_url=ORIGIN,
            module_key="fake", eneo_api_key="service-key", session_secret="x" * 48, cookie_secure=False, **overrides,
        )
        self.upstream = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=eneo), follow_redirects=False)
        test.addAsyncCleanup(self.upstream.aclose)
        self.app = create_app(self.settings, routers=routers, proxy_rules=proxy_rules, http_client=self.upstream)

    def browser(self, user_id: str = "u", *, signed_in: bool = True) -> httpx2.AsyncClient:
        cookies = {SESSION_COOKIE: self.app.state.module_auth.sessions.create(session(user_id))} if signed_in else {}
        client = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=self.app), base_url=ORIGIN, cookies=cookies, headers={"Origin": ORIGIN},
        )
        self.test.addAsyncCleanup(client.aclose)
        return client
