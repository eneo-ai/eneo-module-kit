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

# The request headers that reach Eneo; every other header of the browser's request is dropped (deny by default,
# for headers as for paths). Eneo serves every user on one connection pool and every call carries the service key,
# so a browser's Transfer-Encoding, Forwarded or X-Forwarded-For must not arrive. The credentials are set by the
# module from the session, never taken from the browser. A module that needs more passes
# ``create_app(forward_request_headers=...)``.
FORWARDED_REQUEST_HEADERS = frozenset(
    {"accept", "accept-language", "content-type", "idempotency-key", "if-match", "if-none-match"}
)

# Not even a module may add these: the credentials (the module checks the browser's origin itself, and Eneo
# refuses any origin it does not list) and the headers that frame the request.
_NEVER_FORWARDED_REQUEST_HEADERS = frozenset(
    {
        "authorization",
        "cookie",
        "origin",
        "referer",
        "x-api-key",
        "proxy-authorization",
        "host",
        "content-length",
        "transfer-encoding",
        "connection",
        "keep-alive",
        "te",
        "trailer",
        "upgrade",
    }
)

# Headers we should not forward from upstream response back to client.
_HOP_BY_HOP_RESPONSE_HEADERS = {
    "content-encoding",
    "transfer-encoding",
    "connection",
    "keep-alive",
    "content-length",
}

FORWARDED_REQUEST_HEADERS = frozenset({"accept", "accept-language", "content-type", "idempotency-key", "if-match", "if-none-match"})
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


def _is_unsafe_character(character: str) -> bool:
    return character < " " or character == "\x7f" or character == "\\"


def leaves_route(path: str) -> bool:
    """True if ``path`` could reach another upstream route than the one authorized.

    The allowlist matches on the decoded path, but a percent-encoded dot
    segment such as ``%2E%2E`` still satisfies ``[^/]+`` and would let httpx
    resolve ``a/../b/`` to a different upstream path, and a decoded
    ``?`` or ``#`` would move the rest of the path into a query or fragment.
    A control character (``%00``, ``%0D``) makes httpx raise InvalidURL, which is
    not a request error and would answer 500, and a backslash would go upstream
    literally; both are refused, in the path as decoded and in what a URL parser
    would decode from it once more.
    Reject these before matching so the allowlist keeps meaning exactly the
    routes it spells out.
    """
    return (
        "?" in path
        or "#" in path
        or any(_is_unsafe_character(character) for character in path + unquote(path))
        or any(unquote(segment) in {".", ".."} for segment in path.split("/"))
    )


def proxy_router(rules: Sequence[ProxyRule], forward_request_headers: Sequence[str] = ()) -> APIRouter:
    """``GET|POST|PATCH /api/eneo/{path}``, for the routes in ``rules`` and nothing else.

    Of the browser's request headers only ``FORWARDED_REQUEST_HEADERS`` and ``forward_request_headers`` reach Eneo.
    """
    rules = tuple(rules)
    added = {name.lower() for name in forward_request_headers}
    if refused := sorted(added & _NEVER_FORWARDED_REQUEST_HEADERS):
        raise ValueError(f"forward_request_headers cannot include credential or framing headers: {', '.join(refused)}")
    forwarded_headers = FORWARDED_REQUEST_HEADERS | added
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
        # Forward the allowlisted request headers, and set the credentials from the module-auth session. The
        # header that carries the service key is configured, so it is excluded here, not by name above.
        key_header = settings.eneo_api_key_header_name.lower()
        fwd_headers = {
            name: value
            for name, value in request.headers.items()
            if name.lower() in forwarded_headers and name.lower() != key_header
        }
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
