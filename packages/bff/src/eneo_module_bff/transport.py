from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Iterable, Sequence
from urllib.parse import urlsplit, urlunsplit

import anyio
import httpx2
from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.datastructures import UploadFile
from starlette.types import Receive, Scope, Send

from .auth import SESSION_COOKIE, SignedUrl
from .deps import upstream_auth_headers
from .limits import allow_upload, declared_length, too_large
from .proxy import REDIRECT_STATUSES, forwarded_headers, leaves_route, upstream_redirect, upstream_too_large, upstream_url, uri_too_long
from .settings import Settings, has_control_character
from .upstream import SMALL_ANSWER, SMALL_ANSWER_BYTES, STREAMED, UnboundedAnswer

logger = logging.getLogger("eneo_proxy")

MIN_UPLOAD_PROXY_TIMEOUT_SECONDS = 60.0


def _upload_timeout(settings: Settings, timeout_seconds: float | None = None) -> httpx2.Timeout:
    effective_timeout = settings.upload_proxy_timeout_seconds
    if timeout_seconds is not None:
        effective_timeout = min(
            settings.upload_proxy_timeout_seconds,
            max(MIN_UPLOAD_PROXY_TIMEOUT_SECONDS, timeout_seconds),
        )
    return httpx2.Timeout(
        connect=10.0,
        read=effective_timeout,
        write=effective_timeout,
        pool=30.0,
    )


def _requested_upload_timeout_seconds(request: Request) -> float | None:
    raw = request.headers.get("x-upload-timeout-seconds")
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


# Uploads bypass the catch-all proxy because forwarding
# the browser's raw multipart bytes triggers ReadError from Eneo's load balancer.
# We re-parse and rebuild the multipart with httpx2 instead.
async def forward_upload(request: Request, upstream_path: str) -> Response:
    """Re-post the one file of the request's multipart body to {ENEO_BACKEND_URL}/api/v1/{upstream_path}.

    Call it from a route that has no ``File(...)`` parameter: FastAPI reads a body before it runs a route's
    dependencies, and this reads it itself, so ``Depends(require_session)`` has run before a byte of it is read.
    The body must declare its Content-Length (411), at most ``settings.max_upload_bytes`` (413), and hold one file
    part named ``upload_file`` and no other part (400) whose file name and content type have no control character
    (400: a line break in either would be written into the part headers sent to Eneo). Nothing is left behind if
    the upload is cut off or refused.

    The call to Eneo has a read timeout and a write timeout of settings.upload_proxy_timeout_seconds each, lowered
    (never below 60 s) by the request's X-Upload-Timeout-Seconds header: per phase, as for every call, so no
    total deadline bounds the upload. 504 when one of them runs out, 502 when Eneo cannot be reached, 403 for a path
    that leaves its route.
    """
    settings = request.app.state.settings
    # Upstream URLs are built from decoded path params; a "." / ".." segment or
    # a "?" would resolve to a different Eneo route than the upload endpoints exposed.
    if leaves_route(upstream_path):
        raise HTTPException(status_code=403, detail="Eneo resource is not exposed")
    declared = declared_length(request.headers)
    if declared is None:
        raise HTTPException(status_code=411, detail="Content-Length required")
    if declared > settings.max_upload_bytes:
        raise too_large("Upload too large")
    # Only now, after the route's dependencies and these checks, is the body allowed to be as big as an upload; the
    # limit counts the bytes that arrive, so a Content-Length that lies gets no further than max_upload_bytes.
    allow_upload(request, settings.max_upload_bytes)
    # max_fields=0: no text field beside the file. The files are closed when the block ends, and by Starlette
    # if the parse fails.
    async with request.form(max_files=1, max_fields=0) as form:
        parts = form.multi_items()
        if len(parts) != 1 or parts[0][0] != "upload_file" or not isinstance(parts[0][1], UploadFile):
            raise HTTPException(status_code=400, detail="Exactly one file, named upload_file, is required")
        upload_file = parts[0][1]
        if has_control_character(upload_file.filename) or has_control_character(upload_file.content_type):
            raise HTTPException(status_code=400, detail="The file name and content type must not contain control characters")
        return await _post_file(request, upstream_path, upload_file)


async def _post_file(request: Request, upstream_path: str, upload_file: UploadFile) -> Response:
    settings = request.app.state.settings
    http_client = request.app.state.http
    url = upstream_url(settings.eneo_backend_url, upstream_path)
    await upload_file.seek(0)
    try:
        upstream = await http_client.post(
            url,
            headers=upstream_auth_headers(request),
            files={
                "upload_file": (
                    upload_file.filename,
                    upload_file.file,
                    upload_file.content_type or "application/octet-stream",
                )
            },
            timeout=_upload_timeout(settings, _requested_upload_timeout_seconds(request)),
        )
    except httpx2.InvalidURL:
        raise uri_too_long() from None
    except UnboundedAnswer:
        logger.error("Eneo's answer to an upload is past the bound: url=%s", url)
        return upstream_too_large()
    except httpx2.TimeoutException:
        logger.exception("Upload timed out: url=%s", url)
        return JSONResponse(
            status_code=504,
            content={
                "error": "upstream_upload_timeout",
                "detail": "Eneo did not complete the upload before the timeout.",
            },
        )
    except httpx2.RequestError:
        logger.exception("Upload failed: url=%s", url)
        return JSONResponse(
            status_code=502,
            content={
                "error": "upstream_unreachable",
                "detail": "Eneo could not be reached.",
            },
        )

    if upstream.status_code in REDIRECT_STATUSES:
        logger.error("Upload was answered with a redirect: url=%s status=%s", url, upstream.status_code)
        return upstream_redirect()

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )


# ---------------------------------------------------------------------------
# Files of a run, streamed same-origin: audio for playback, artifacts to open
# or download.
#
# Eneo hands out a short-lived signed URL per file. The browser must not use it
# directly: the module's CSP only allows same-origin media and frames, and the
# URL is a bearer credential for the file. The module backend mints the URL
# with its own credentials, caches it per session for the file's lifetime so
# the browser's many Range requests do not each mint (and audit-log) a new
# one, and streams the bytes through with Range semantics intact.
# ---------------------------------------------------------------------------

_SIGNED_URL_TTL_SECONDS = 15 * 60
_SIGNED_URL_REFRESH_MARGIN_SECONDS = 60
_STREAM_FORWARD_REQUEST_HEADERS = frozenset({"range", "if-range", "accept"})
_STREAM_FORWARD_RESPONSE_HEADERS = frozenset(
    {
        "content-disposition",
        "content-type",
        "content-length",
        "content-range",
        "content-encoding",
        "accept-ranges",
        "etag",
        "last-modified",
    }
)


# Eneo is asked for an inline file and a user's upload decides its own content type, so a file is shown inline
# from the module's origin only if its media type cannot run script. Anything else is an attachment.
# ``stream_signed(inline_types=...)`` adds to this; an entry is a media type or ``type/*``.
INLINE_MEDIA_TYPES = ("audio/*", "video/*", "application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp")


def _may_be_shown_inline(media_type: str, allowed: Iterable[str]) -> bool:
    return any(
        media_type.startswith(pattern[:-1]) if pattern.endswith("/*") else media_type == pattern
        for pattern in (entry.lower() for entry in allowed)
    )


def _attachment(disposition: str | None) -> str:
    """``attachment``, keeping the parameters Eneo sent (the file name)."""
    parameters = (disposition or "").partition(";")[2].strip()
    return f"attachment; {parameters}" if parameters else "attachment"


# The signed URLs are kept by the session store (ModuleSessionStore.signed_url and friends), by session and
# mint path, one URL per file, so each ends with its session.


def _rebase_signed_url(signed_url: str, base_url: str) -> str:
    """Point a signed URL at the Eneo host the module backend can reach.

    Eneo builds signed URLs on its public base URL; on the module network the
    backend reaches Eneo on ``ENEO_BACKEND_URL`` instead. Only scheme and host
    change — the path and the signed query survive untouched.
    """
    signed = urlsplit(signed_url)
    base = urlsplit(base_url)
    return urlunsplit((base.scheme, base.netloc, signed.path, signed.query, ""))


class _InvalidMintAnswer(Exception):
    """Eneo answered the mint request with something the module cannot use."""


def _read_mint_answer(upstream: httpx2.Response, base_url: str, now: float) -> tuple[str, float]:
    """The signed URL (on the host the module reaches Eneo on) and when it expires, from Eneo's answer."""
    try:
        payload = upstream.json()
        url = payload["url"]
        # The default only when the key is missing or null: any other value was supplied, so it must be a number
        # (0, false, "", [] and {} are not "missing", and none of them is one).
        expires_at = payload.get("expires_at")
        if expires_at is None:
            expires_at = now + _SIGNED_URL_TTL_SECONDS
        elif isinstance(expires_at, bool):
            raise ValueError("expires_at is not a number")
        expires_at = float(expires_at)
        # Only the path and the signed query of the URL are used, on the host the module reaches Eneo on; but a URL
        # of another kind (ftp, file, javascript, a relative one) is not what Eneo's signed-URL route returns.
        parsed = urlsplit(url) if isinstance(url, str) else None
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        # Not JSON, not an object, no url, an expires_at that is not a number (or too big for one), or a URL that
        # cannot be parsed.
        raise _InvalidMintAnswer from None
    if parsed is None or parsed.scheme not in {"http", "https"} or not parsed.netloc or not (math.isfinite(expires_at) and expires_at > 0):
        raise _InvalidMintAnswer
    rebased = _rebase_signed_url(url, base_url)
    try:
        # What the client will build the request from, before the URL is kept: one it refuses (a NUL, too long)
        # would be cached, and every later request of the session would fail on it.
        httpx2.URL(rebased)
    except httpx2.InvalidURL:
        raise _InvalidMintAnswer from None
    return rebased, expires_at


async def _signed_url(request: Request, session_id: str, mint_path: str, unavailable: str) -> str:
    settings = request.app.state.settings
    http_client = request.app.state.http
    sessions = request.app.state.module_auth.sessions
    now = time.time()
    cached = sessions.signed_url(session_id, mint_path)
    if cached and cached.expires_at - _SIGNED_URL_REFRESH_MARGIN_SECONDS > now:
        return cached.url

    try:
        upstream = await http_client.post(
            upstream_url(settings.eneo_backend_url, mint_path),
            json={
                "expires_in": _SIGNED_URL_TTL_SECONDS,
                "content_disposition": "inline",
            },
            headers=upstream_auth_headers(request),
            extensions=SMALL_ANSWER,
        )
    except httpx2.InvalidURL:
        raise uri_too_long() from None
    except UnboundedAnswer:
        logger.error("Signed URL answer is past the bound: path=%s", mint_path)
        raise _InvalidMintAnswer from None
    except httpx2.RequestError:
        logger.exception("Signed URL request failed: path=%s", mint_path)
        raise HTTPException(status_code=502, detail="Eneo could not be reached.")
    if upstream.status_code >= 400:
        try:
            detail = upstream.json()
        except ValueError:
            detail = {"detail": unavailable}
        raise HTTPException(status_code=upstream.status_code, detail=detail)

    try:
        url, expires_at = _read_mint_answer(upstream, settings.eneo_backend_url, now)
    except _InvalidMintAnswer:
        logger.error("Signed URL answer is not usable: path=%s", mint_path)
        raise
    sessions.remember_signed_url(session_id, mint_path, SignedUrl(url=url, expires_at=expires_at))
    return url


# How long closing Eneo's answer may take: a peer that does not answer the close does not hold the response.
_STREAM_CLOSE_TIMEOUT_SECONDS = 2


async def _close(upstream: httpx2.Response) -> None:
    """Close Eneo's answer. Shielded from the cancellation that may be ending the request, bounded, and a failure
    is logged: closing is cleanup, so it never replaces the answer or the error of the response it belongs to."""
    with anyio.move_on_after(_STREAM_CLOSE_TIMEOUT_SECONDS, shield=True):
        try:
            await upstream.aclose()
        except Exception:
            logger.warning("File stream: closing Eneo's answer failed", exc_info=True)


class _SlotStreamingResponse(StreamingResponse):
    """A streamed file that holds one of the app's stream slots until Eneo's answer is closed, however the
    response ends: the file finished, an error in the body, the client went away, or the request was cancelled.
    A BackgroundTask would run only after a stream that succeeded, and a generator is closed only if it is
    resumed, so the closing belongs to the whole life of the response."""

    def __init__(self, upstream: httpx2.Response, slots: asyncio.Semaphore, **kwargs: object) -> None:
        super().__init__(upstream.aiter_raw(), **kwargs)
        self._upstream = upstream
        self._slots = slots

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            try:
                await _close(self._upstream)
            finally:
                # The slot bounds the connections open to Eneo, so it is given back after the close.
                self._slots.release()


async def stream_signed(
    request: Request,
    *resource: str,
    mint_path: str,
    unavailable: str,
    inline_types: Sequence[str] = (),
) -> Response:
    """Mint (or reuse, per session and mint path) Eneo's signed URL and stream the file through with Range.

    ``resource`` are the path ids that went into ``mint_path``; one that leaves its route is a 403. The file is
    an attachment unless its media type is in ``INLINE_MEDIA_TYPES`` or ``inline_types``. At most
    ``settings.max_concurrent_streams`` files stream at once: the next is a 503 with Retry-After, at once, so
    that the connections a stream would hold stay free for the API.
    """
    if any(leaves_route(part) for part in resource):
        raise HTTPException(status_code=403, detail="Eneo resource is not exposed")
    slots = request.app.state.stream_slots
    if slots.locked():
        return JSONResponse(
            status_code=503,
            content={"error": "streams_busy", "detail": "Too many files are being streamed. Try again shortly."},
            headers={"Retry-After": "2"},
        )
    await slots.acquire()
    response: Response | None = None
    try:
        response = await _stream_file(request, slots, resource, mint_path, unavailable, inline_types)
        return response
    finally:
        # A file that is streaming keeps its slot until its response is over; anything else gives it back now.
        if not isinstance(response, _SlotStreamingResponse):
            slots.release()


async def _read_small(upstream: httpx2.Response) -> bytes:
    """The body of a streamed answer that is an error, closed; empty if it is longer than an error is."""
    body = bytearray()
    try:
        async for chunk in upstream.aiter_raw():
            body += chunk
            if len(body) > SMALL_ANSWER_BYTES:
                return b""
    finally:
        await _close(upstream)
    return bytes(body)


async def _stream_file(
    request: Request,
    slots: asyncio.Semaphore,
    resource: tuple[str, ...],
    mint_path: str,
    unavailable: str,
    inline_types: Sequence[str],
) -> Response:
    http_client = request.app.state.http
    sessions = request.app.state.module_auth.sessions
    session_id = request.cookies.get(SESSION_COOKIE) or ""
    # Before anything is asked of Eneo: a header httpx2 cannot write is the client's mistake, not a reason to mint.
    fwd_headers = forwarded_headers(request.headers, _STREAM_FORWARD_REQUEST_HEADERS)
    try:
        url = await _signed_url(request, session_id, mint_path, unavailable)
    except _InvalidMintAnswer:
        return JSONResponse(
            status_code=502,
            content={"error": "upstream_invalid", "detail": "Eneo answered with something the module cannot use."},
        )

    upstream_request = http_client.build_request("GET", url, headers=fwd_headers, extensions=STREAMED)
    try:
        upstream = await http_client.send(upstream_request, stream=True)
    except httpx2.RequestError:
        logger.exception("File stream request failed: path=%s", mint_path)
        return JSONResponse(
            status_code=502,
            content={"error": "upstream_unreachable", "detail": "Eneo could not be reached."},
        )

    if upstream.status_code in REDIRECT_STATUSES:
        # Not a file: the URL is not worth keeping either, and the stream is closed unread.
        sessions.forget_signed_url(session_id, mint_path)
        await _close(upstream)
        logger.error("File stream was answered with a redirect: path=%s status=%s", mint_path, upstream.status_code)
        return upstream_redirect()

    if upstream.status_code >= 400:
        # A rejected token is not worth keeping around; the next request mints anew.
        sessions.forget_signed_url(session_id, mint_path)
        try:
            body = await _read_small(upstream)
        except httpx2.RequestError:
            # Cut off or silent while its body was read: no more an answer than one that never came.
            logger.exception("File stream answer could not be read: path=%s status=%s", mint_path, upstream.status_code)
            return JSONResponse(
                status_code=502,
                content={"error": "upstream_unreachable", "detail": "Eneo could not be reached."},
            )
        detail: object = unavailable
        if body and upstream.headers.get("content-type", "").startswith("application/json"):
            try:
                detail = httpx2.Response(200, content=body).json()
            except ValueError:
                pass
        raise HTTPException(status_code=upstream.status_code, detail=detail)

    try:
        return _SlotStreamingResponse(
            upstream, slots, status_code=upstream.status_code, headers=_file_headers(upstream, inline_types)
        )
    except Exception:
        # A header that cannot be written back: the response never existed to close Eneo's answer.
        await _close(upstream)
        raise


def _file_headers(upstream: httpx2.Response, inline_types: Sequence[str]) -> dict[str, str]:
    resp_headers = {
        k.lower(): v
        for k, v in upstream.headers.items()
        if k.lower() in _STREAM_FORWARD_RESPONSE_HEADERS
    }
    media_type = resp_headers.get("content-type", "").split(";")[0].strip().lower()
    if not _may_be_shown_inline(media_type, (*INLINE_MEDIA_TYPES, *inline_types)):
        resp_headers["content-disposition"] = _attachment(resp_headers.get("content-disposition"))
    resp_headers["x-content-type-options"] = "nosniff"
    resp_headers["Cache-Control"] = "private, no-store"
    return resp_headers
