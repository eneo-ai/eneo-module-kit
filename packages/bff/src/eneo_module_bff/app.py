from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import httpx2
from fastapi import APIRouter, FastAPI

from . import branding
from .auth import ModuleAuth
from .limits import BodyLimitMiddleware
from .proxy import ProxyRule, proxy_router
from .settings import Settings, load_settings
from .web import add_security_headers, serve_web


def create_app(
    settings: Settings | None = None,  # None: load_settings()
    *,
    title: str = "Eneo module",
    routers: Sequence[APIRouter] = (),  # the module's own routes
    proxy_rules: Sequence[ProxyRule] = (),  # the routes under /api/eneo; none by default
    forward_request_headers: Sequence[str] = (),  # added to the request headers the proxy forwards
    static_dir: Path | None = None,  # the built UI, served last
    security_headers: dict[str, str] | None = None,  # replaces defaults, e.g. Permissions-Policy microphone=(self)
    http_client: httpx2.AsyncClient | None = None,  # tests inject one; otherwise the lifespan owns one
) -> FastAPI:
    """The module's app: auth under /api/auth, health, branding. Everything hangs off ``app.state``.

    ``app.state.settings``, ``app.state.http`` and ``app.state.module_auth`` are what the route
    dependencies and the proxy read. No client is a module global.

    Routes are matched in the order they are registered: the kit's own, then ``routers``, then the
    proxy under /api/eneo, then the built UI. A module's route wins over the proxy and the page, and
    cannot replace a route of the kit. The module declares its own ``Depends(require_session)``.
    """
    if settings is None:
        settings = load_settings()
    owns_client = http_client is None
    if http_client is None:
        # At once, not at start-up: the auth router needs its ModuleAuth before the app starts.
        # pool=5: a call waits at most 5 s for a free connection. With the default 60 s, a pool held full by
        # streams made every API call a 502 after a minute.
        http_client = httpx2.AsyncClient(
            timeout=httpx2.Timeout(60.0, connect=10.0, pool=5.0),
            follow_redirects=False,
        )

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            # An injected client belongs to whoever injected it.
            if owns_client:
                await http_client.aclose()

    app = FastAPI(title=title, lifespan=lifespan)
    app.state.settings = settings
    app.state.http = http_client
    # One slot per file streaming at once (transport.stream_signed): the rest are 503, and the pool keeps room for the API.
    app.state.stream_slots = asyncio.Semaphore(settings.max_concurrent_streams)
    app.state.module_auth = ModuleAuth(settings=settings, http_client=http_client)
    # Added before the security headers, so that the 413 it answers carries them.
    app.add_middleware(BodyLimitMiddleware, max_body_bytes=settings.max_body_bytes, max_upload_bytes=settings.max_upload_bytes)
    add_security_headers(app, security_headers)
    app.include_router(app.state.module_auth.router, prefix="/api/auth")

    @app.get("/api/healthz")
    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(branding.router)
    for router in routers:
        app.include_router(router)
    app.include_router(proxy_router(proxy_rules, forward_request_headers))
    if static_dir is not None:
        serve_web(app, static_dir)
    return app
