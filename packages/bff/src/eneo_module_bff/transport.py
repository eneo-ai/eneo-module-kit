from __future__ import annotations

import logging
import math
import time
from collections.abc import Iterable, Sequence
from urllib.parse import urlsplit, urlunsplit

import httpx2
from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask
from starlette.datastructures import UploadFile

from .auth import SESSION_COOKIE, SignedUrl
from .deps import upstream_auth_headers
from .limits import allow_upload, declared_length, too_large
from .proxy import REDIRECT_STATUSES, leaves_route, upstream_redirect
from .settings import Settings

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


def _has_control_character(value: str | None) -> bool:
    return value is not None and any(character < " " or character == "\x7f" for character in value)


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

    The time budget is settings.upload_proxy_timeout_seconds, lowered (never below 60 s) by the request's
    X-Upload-Timeout-Seconds header. 504 on timeout, 502 when Eneo cannot be reached, 403 for a path that
    leaves its route.
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
        if _has_control_character(upload_file.filename) or _has_control_character(upload_file.content_type):
            raise HTTPException(status_code=400, detail="The file name and content type must not contain control characters")
        return await _post_file(request, upstream_path, upload_file)


async def _post_file(request: Request, upstream_path: str, upload_file: UploadFile) -> Response:
    settings = request.app.state.settings
    http_client = request.app.state.http
    upstream_url = f"{settings.eneo_backend_url}/api/v1/{upstream_path}"
    await upload_file.seek(0)
    try:
        upstream = await http_client.post(
            upstream_url,
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
    except httpx2.TimeoutException:
        logger.exception("Upload timed out: url=%s", upstream_url)
        return JSONResponse(
            status_code=504,
            content={
                "error": "upstream_upload_timeout",
                "detail": "Eneo did not complete the upload before the timeout.",
            },
        )
    except httpx2.RequestError:
        logger.exception("Upload failed: url=%s", upstream_url)
        return JSONResponse(
            status_code=502,
            content={
                "error": "upstream_unreachable",
                "detail": "Eneo could not be reached.",
            },
        )

    if upstream.status_code in REDIRECT_STATUSES:
        logger.error("Upload was answered with a redirect: url=%s status=%s", upstream_url, upstream.status_code)
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
        expires_at = payload.get("expires_at") or now + _SIGNED_URL_TTL_SECONDS
        if isinstance(expires_at, bool):
            raise ValueError("expires_at is not a number")
        expires_at = float(expires_at)
        # Only the path and the signed query of the URL are used, on the host the module reaches Eneo on; but a URL
        # of another kind (ftp, file, javascript, a relative one) is not what Eneo's signed-URL route returns.
        parsed = urlsplit(url) if isinstance(url, str) else None
    except (ValueError, TypeError, KeyError, AttributeError):
        # Not JSON, not an object, no url, an expires_at that is not a number, or a URL that cannot be parsed.
        raise _InvalidMintAnswer from None
    if parsed is None or parsed.scheme not in {"http", "https"} or not parsed.netloc or not math.isfinite(expires_at):
        raise _InvalidMintAnswer
    return _rebase_signed_url(url, base_url), expires_at


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
            f"{settings.eneo_backend_url}/api/v1/{mint_path}",
            json={
                "expires_in": _SIGNED_URL_TTL_SECONDS,
                "content_disposition": "inline",
            },
            headers=upstream_auth_headers(request),
        )
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


async def stream_signed(
    request: Request,
    *resource: str,
    mint_path: str,
    unavailable: str,
    inline_types: Sequence[str] = (),
) -> Response:
    """Mint (or reuse, per session and mint path) Eneo's signed URL and stream the file through with Range.

    ``resource`` are the path ids that went into ``mint_path``; one that leaves its route is a 403. The file is
    an attachment unless its media type is in ``INLINE_MEDIA_TYPES`` or ``inline_types``.
    """
    http_client = request.app.state.http
    sessions = request.app.state.module_auth.sessions
    if any(leaves_route(part) for part in resource):
        raise HTTPException(status_code=403, detail="Eneo resource is not exposed")

    session_id = request.cookies.get(SESSION_COOKIE) or ""
    try:
        url = await _signed_url(request, session_id, mint_path, unavailable)
    except _InvalidMintAnswer:
        return JSONResponse(
            status_code=502,
            content={"error": "upstream_invalid", "detail": "Eneo answered with something the module cannot use."},
        )

    fwd_headers = {
        name: value
        for name, value in request.headers.items()
        if name.lower() in _STREAM_FORWARD_REQUEST_HEADERS
    }
    upstream_request = http_client.build_request("GET", url, headers=fwd_headers)
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
        await upstream.aclose()
        logger.error("File stream was answered with a redirect: path=%s status=%s", mint_path, upstream.status_code)
        return upstream_redirect()

    if upstream.status_code >= 400:
        # A rejected token is not worth keeping around; the next request mints anew.
        sessions.forget_signed_url(session_id, mint_path)
        try:
            body = await upstream.aread()
        finally:
            await upstream.aclose()
        detail: object = unavailable
        if upstream.headers.get("content-type", "").startswith("application/json"):
            try:
                detail = httpx2.Response(200, content=body).json()
            except ValueError:
                pass
        raise HTTPException(status_code=upstream.status_code, detail=detail)

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
    return StreamingResponse(
        upstream.aiter_raw(),
        status_code=upstream.status_code,
        headers=resp_headers,
        background=BackgroundTask(upstream.aclose),
    )
