from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Sequence
from typing import NamedTuple
from urllib.parse import unquote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from .deps import require_same_origin, require_session, upstream_auth_headers

logger = logging.getLogger("eneo_proxy")

# Headers we should not forward from incoming request to upstream.
# The header that carries the service key is added per request, from the app's settings.
_HOP_BY_HOP_REQUEST_HEADERS = {
    "host",
    "connection",
    "content-length",
    "accept-encoding",
    "authorization",
    "cookie",
    "x-api-key",
    # Intern routing-header — Eneo ska inte se den.
    "x-space-id",
    # Intern proxy-budget för stora uploads.
    "x-upload-timeout-seconds",
    # The module checks the browser's origin itself; Eneo refuses any origin it does not list,
    # so the module's own hostname passed on would fail every write in production.
    "origin",
    "referer",
}

# Headers we should not forward from upstream response back to client.
_HOP_BY_HOP_RESPONSE_HEADERS = {
    "content-encoding",
    "transfer-encoding",
    "connection",
    "keep-alive",
    "content-length",
}

RESOURCE_ID = r"[^/]+"


class ProxyRule(NamedTuple):
    methods: frozenset[str]
    # Matched with fullmatch against the path after /api/eneo/.
    pattern: re.Pattern[str]


def rule(methods: str | Iterable[str], pattern: str) -> ProxyRule:
    """One allowed route: ``rule("GET", r"things/$")`` or ``rule({"GET", "POST"}, rf"things/{RESOURCE_ID}/$")``."""
    return ProxyRule(
        frozenset({methods} if isinstance(methods, str) else methods),
        re.compile(pattern),
    )


def _proxy_route_is_allowed(rules: Sequence[ProxyRule], method: str, path: str) -> bool:
    return any(
        method in methods and pattern.fullmatch(path) is not None
        for methods, pattern in rules
    )


def leaves_route(path: str) -> bool:
    """True if ``path`` could reach another upstream route than the one authorized.

    The allowlist matches on the decoded path, but a percent-encoded dot
    segment such as ``%2E%2E`` still satisfies ``[^/]+`` and would let httpx
    resolve ``a/../b/`` to a different upstream path, and a decoded
    ``?`` or ``#`` would move the rest of the path into a query or fragment.
    Reject these before matching so the allowlist keeps meaning exactly the
    routes it spells out.
    """
    return (
        "?" in path
        or "#" in path
        or any(unquote(segment) in {".", ".."} for segment in path.split("/"))
    )


def proxy_router(rules: Sequence[ProxyRule]) -> APIRouter:
    """``GET|POST|PATCH /api/eneo/{path}``, for the routes in ``rules`` and nothing else."""
    rules = tuple(rules)
    router = APIRouter()

    @router.api_route(
        "/api/eneo/{path:path}",
        methods=["GET", "POST", "PATCH"],
        dependencies=[
            Depends(require_session),
            Depends(require_same_origin),
        ],
    )
    async def eneo_proxy(path: str, request: Request) -> Response:
        settings = request.app.state.settings
        http_client = request.app.state.http
        if leaves_route(path) or not _proxy_route_is_allowed(rules, request.method, path):
            raise HTTPException(status_code=403, detail="Eneo resource is not exposed")
        upstream_url = f"{settings.eneo_backend_url}/api/v1/{path}"
        # Forward request headers, but replace browser-controlled credentials with
        # the credentials owned by the configured module-auth session.
        skipped_headers = _HOP_BY_HOP_REQUEST_HEADERS | {settings.eneo_api_key_header_name.lower()}
        fwd_headers: dict[str, str] = {}
        for name, value in request.headers.items():
            if name.lower() in skipped_headers:
                continue
            fwd_headers[name] = value
        fwd_headers.update(upstream_auth_headers(request))

        body = await request.body()

        try:
            upstream = await http_client.request(
                method=request.method,
                url=upstream_url,
                params=request.query_params,
                content=body if body else None,
                headers=fwd_headers,
            )
        except httpx.RequestError:
            logger.exception(
                "Upstream request failed: method=%s url=%s",
                request.method,
                upstream_url,
            )
            return JSONResponse(
                status_code=502,
                content={
                    "error": "upstream_unreachable",
                    "detail": "Eneo could not be reached.",
                },
            )

        resp_headers = {
            k: v
            for k, v in upstream.headers.items()
            if k.lower() not in _HOP_BY_HOP_RESPONSE_HEADERS
        }

        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=resp_headers,
            media_type=upstream.headers.get("content-type"),
        )

    return router
