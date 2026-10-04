from __future__ import annotations

import asyncio
import gzip
import logging
import re
from collections.abc import Collection, Iterable, Sequence
from typing import NamedTuple
from urllib.parse import quote

import httpx2
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers

from .deps import require_same_origin, require_session, upstream_auth_headers
from .settings import CREDENTIAL_AND_FRAMING_HEADERS
from .upstream import UnboundedAnswer
from .web import NO_STORE

logger = logging.getLogger("eneo_proxy")

# The request headers that reach Eneo; every other header of the browser's request is dropped (deny by default,
# for headers as for paths). Eneo serves every user on one connection pool and every call carries the service key,
# so a browser's Transfer-Encoding, Forwarded or X-Forwarded-For must not arrive. The credentials are set by the
# module from the session, never taken from the browser. A module that needs more passes
# ``create_app(forward_request_headers=...)``.
FORWARDED_REQUEST_HEADERS = frozenset(
    {"accept", "accept-language", "content-type", "idempotency-key", "if-match", "if-none-match"}
)

# Headers we should not forward from upstream response back to client. Eneo's cookies are not the browser's:
# several would be merged into one line, and one named like the module's session would replace it. Its Location
# names Eneo's own host, which the browser cannot reach and which says how the network is laid out. Its caching and
# policy headers speak for Eneo's origin, not the module's: the module's own (``web.SECURITY_HEADERS``, ``NO_STORE``)
# stand, and a page that Eneo's policy let be framed, or its answer kept, would be the module's.
_UNFORWARDED_RESPONSE_HEADERS = {
    "content-encoding",
    "transfer-encoding",
    "connection",
    "keep-alive",
    "content-length",
    "set-cookie",
    "location",
    "cache-control",
    "content-security-policy",
    "x-frame-options",
    "permissions-policy",
    "referrer-policy",
}

# A JSON answer of the proxy of at least this many bytes is gzipped for a client that accepts it. Smaller ones cost more
# to compress than they save.
_COMPRESS_MIN_BYTES = 1024

# The module never follows a redirect, and no route of a module is expected to redirect, so one from Eneo is an
# error, not an answer for the browser. (304 is not one: If-None-Match is forwarded, and a conditional read gets it.)
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


def upstream_too_large() -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={
            "error": "upstream_too_large",
            "detail": "Eneo's answer is larger than the module reads.",
        },
    )


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


def upstream_url(base_url: str, path: str) -> str:
    """``{base_url}/api/v1/{path}``, with ``path`` encoded as the logical path it is.

    ``path`` is the path as the module authorised it, already decoded once: a ``%2F`` in it is the three characters
    of an id, not a separator. httpx2 sends an escape it finds as it is, and Eneo decodes it once more, so
    ``things/a%2Fexport/`` would arrive as ``things/a/export/``, a route the allowlist never saw. Every character
    that is not a letter, a digit, ``_.-~`` or the ``/`` between segments is encoded here, ``%`` included.
    """
    return f"{base_url}/api/v1/{quote(path, safe='/')}"


def uri_too_long() -> HTTPException:
    """What an ``httpx2.InvalidURL`` from a path or query the client will not write is answered with."""
    return HTTPException(status_code=414, detail="Request URI too long")


def forwarded_headers(headers: Headers, allowed: Collection[str], *, skip: str = "") -> dict[str, str]:
    """The request ``headers`` whose lower-case name is in ``allowed`` (but not ``skip``).

    A value that is not ASCII is a 400: httpx2 writes a str value as ASCII and raises UnicodeEncodeError for any
    other, which would be a 500 for something a client sent.
    """
    forwarded = {name: value for name, value in headers.items() if name.lower() in allowed and name.lower() != skip}
    if not all(value.isascii() for value in forwarded.values()):
        raise HTTPException(status_code=400, detail="A request header holds characters that cannot be forwarded")
    return forwarded


def _accepted_encodings(accept_encoding: str | None) -> set[str]:
    """The content codings a client names with a quality above zero (``gzip`` is one, ``gzip;q=0`` is not)."""
    accepted = set()
    for part in (accept_encoding or "").split(","):
        name, *parameters = (piece.strip() for piece in part.split(";"))
        quality = 1.0
        for parameter in parameters:
            key, _, value = parameter.partition("=")
            if key.strip().lower() == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        if name and quality > 0:
            accepted.add(name.lower())
    return accepted


def _is_json(content_type: str | None) -> bool:
    media_type = (content_type or "").split(";")[0].strip().lower()
    return media_type == "application/json" or (media_type.startswith("application/") and media_type.endswith("+json"))


async def _compress_json(request: Request, upstream: httpx2.Response, headers: dict[str, str]) -> bytes:
    """The body to send for a proxied answer: Eneo's content, gzipped when that is allowed, with ``headers`` changed to say so.

    Only a whole JSON answer (2xx but not 204 or 206, no Content-Range, to a request without a Range) of at least
    ``_COMPRESS_MIN_BYTES`` is compressed, and only for a client that accepts gzip. An answer that could be gzipped
    gets ``Vary: Accept-Encoding`` either way. The compression runs off the event loop (zlib lets go of the GIL): a
    WebSocket relay or a file stream of the module shares it.
    """
    content = upstream.content
    if (
        not 200 <= upstream.status_code < 300
        or upstream.status_code in {204, 206}
        or len(content) < _COMPRESS_MIN_BYTES
        or not _is_json(upstream.headers.get("content-type"))
        or "content-range" in upstream.headers
        or "range" in request.headers
    ):
        return content
    headers["Vary"] = "Accept-Encoding"
    if "gzip" not in _accepted_encodings(request.headers.get("accept-encoding")):
        return content
    headers["Content-Encoding"] = "gzip"
    for name in [name for name in headers if name.lower() == "etag" and not headers[name].startswith("W/")]:
        headers[name] = "W/" + headers[name]  # another body of the same resource: no longer a strong validator
    return await asyncio.to_thread(gzip.compress, content, 6)


def proxy_router(rules: Sequence[ProxyRule], forward_request_headers: Sequence[str] = ()) -> APIRouter:
    """``GET|POST|PATCH /api/eneo/{path}``, for the routes in ``rules`` and nothing else.

    Of the browser's request headers only ``FORWARDED_REQUEST_HEADERS`` and ``forward_request_headers`` reach Eneo.
    """
    rules = tuple(rules)
    added = {name.lower() for name in forward_request_headers}
    if refused := sorted(added & CREDENTIAL_AND_FRAMING_HEADERS):
        raise ValueError(f"forward_request_headers cannot include credential or framing headers: {', '.join(refused)}")
    allowed_headers = FORWARDED_REQUEST_HEADERS | added
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
        url = upstream_url(settings.eneo_backend_url, path)
        # Forward the allowlisted request headers, and set the credentials from the module-auth session. The
        # header that carries the service key is configured, so it is excluded here, not by name above.
        fwd_headers = forwarded_headers(request.headers, allowed_headers, skip=settings.eneo_api_key_header_name.lower())
        fwd_headers.update(upstream_auth_headers(request))

        body = await request.body()  # at most Settings.max_body_bytes: the body limit counts it as it arrives

        try:
            upstream = await http_client.request(
                method=request.method,
                url=url,
                params=request.query_params,
                content=body if body else None,
                headers=fwd_headers,
            )
        except httpx2.InvalidURL:
            raise uri_too_long() from None
        except UnboundedAnswer:
            logger.error("Eneo's answer is past the bound: method=%s url=%s", request.method, url)
            return upstream_too_large()
        except httpx2.RequestError:
            logger.exception(
                "Upstream request failed: method=%s url=%s",
                request.method,
                url,
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
                url,
                upstream.status_code,
            )
            return upstream_redirect()

        resp_headers = {
            k: v
            for k, v in upstream.headers.items()
            if k.lower() not in _UNFORWARDED_RESPONSE_HEADERS
        }
        # A response is one user's: no cache keeps it, whatever Eneo said.
        resp_headers["Cache-Control"] = NO_STORE
        content = await _compress_json(request, upstream, resp_headers)

        return Response(
            content=content,
            status_code=upstream.status_code,
            headers=resp_headers,
            media_type=upstream.headers.get("content-type"),
        )

    return router
