from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Sequence
from typing import NamedTuple

import httpx2
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

# Headers we should not forward from upstream response back to client. Eneo's cookies are not the browser's:
# several would be merged into one line, and one named like the module's session would replace it. Its Location
# names Eneo's own host, which the browser cannot reach and which says how the network is laid out.
_UNFORWARDED_RESPONSE_HEADERS = {
    "content-encoding",
    "transfer-encoding",
    "connection",
    "keep-alive",
    "content-length",
    "set-cookie",
    "location",
}

# The module never follows a redirect, and no route of a module is expected to redirect, so one from Eneo is an
# error, not an answer for the browser. (304 is not one: If-None-Match is forwarded, and a conditional read gets it.)
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


def upstream_redirect() -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={
            "error": "upstream_redirect",
            "detail": "Eneo answered with a redirect, which the module does not follow.",
        },
    )

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


# A control character or a backslash. What a URL parser would decode from the path once more has one exactly
# when the path has a %XX that decodes to one, so the second pattern covers that without decoding anything.
_UNSAFE_CHARACTER = re.compile(r"[\x00-\x1f\x7f\\]")
_ENCODED_UNSAFE_CHARACTER = re.compile(r"%(?:[01][0-9a-fA-F]|7[fF]|5[cC])")
# A path segment that is a dot or two, each written as itself or percent-encoded (".", "..", "%2e%2E", ".%2e"):
# what ``unquote(segment) in {".", ".."}`` means, as a set lookup over the segments.
_DOT_SEGMENTS = frozenset({".", "%2e", "%2E"}) | frozenset(
    first + second for first in (".", "%2e", "%2E") for second in (".", "%2e", "%2E")
)


def leaves_route(path: str) -> bool:
    """True if ``path`` could reach another upstream route than the one authorized.

    The allowlist matches on the decoded path, but a percent-encoded dot
    segment such as ``%2E%2E`` still satisfies ``[^/]+`` and would let httpx2
    resolve ``a/../b/`` to a different upstream path, and a decoded
    ``?`` or ``#`` would move the rest of the path into a query or fragment.
    A control character (``%00``, ``%0D``) makes httpx2 raise InvalidURL, which is
    not a request error and would answer 500, and a backslash would go upstream
    literally; both are refused, in the path as decoded and in what a URL parser
    would decode from it once more.
    Reject these before matching so the allowlist keeps meaning exactly the
    routes it spells out.
    """
    # Compiled searches, not Python loops: a loop per character cost 7.5 ms on a 64 KB path, on every request.
    return (
        "?" in path
        or "#" in path
        or _UNSAFE_CHARACTER.search(path) is not None
        or _ENCODED_UNSAFE_CHARACTER.search(path) is not None
        or not _DOT_SEGMENTS.isdisjoint(path.split("/"))
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

        body = await request.body()  # at most Settings.max_body_bytes: the body limit counts it as it arrives

        try:
            upstream = await http_client.request(
                method=request.method,
                url=upstream_url,
                params=request.query_params,
                content=body if body else None,
                headers=fwd_headers,
            )
        except httpx2.RequestError:
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

        if upstream.status_code in REDIRECT_STATUSES:
            logger.error(
                "Eneo answered with a redirect: method=%s url=%s status=%s",
                request.method,
                upstream_url,
                upstream.status_code,
            )
            return upstream_redirect()

        resp_headers = {
            k: v
            for k, v in upstream.headers.items()
            if k.lower() not in _UNFORWARDED_RESPONSE_HEADERS
        }
        # A response is one user's: no cache keeps it unless Eneo said how it may be kept.
        if not any(name.lower() == "cache-control" for name in resp_headers):
            resp_headers["Cache-Control"] = "private, no-store"

        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=resp_headers,
            media_type=upstream.headers.get("content-type"),
        )

    return router
