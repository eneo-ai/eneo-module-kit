from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Sequence
from typing import NamedTuple
from urllib.parse import urlsplit, urlunsplit

import httpx2
from fastapi import HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from .auth import SESSION_COOKIE
from .deps import upstream_auth_headers
from .proxy import leaves_route
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


# Uploads bypass the catch-all proxy because forwarding
# the browser's raw multipart bytes triggers ReadError from Eneo's load balancer.
# We re-parse and rebuild the multipart with httpx2 instead.
async def forward_upload(request: Request, upstream_path: str, upload_file: UploadFile) -> Response:
    """Re-post one multipart file to {ENEO_BACKEND_URL}/api/v1/{upstream_path} with both credentials.

    The time budget is settings.upload_proxy_timeout_seconds, lowered (never below 60 s) by the request's
    X-Upload-Timeout-Seconds header. 504 on timeout, 502 when Eneo cannot be reached, 403 for a path that
    leaves its route.
    """
    settings = request.app.state.settings
    http_client = request.app.state.http
    # Upstream URLs are built from decoded path params; a "." / ".." segment or
    # a "?" would resolve to a different Eneo route than the upload endpoints exposed.
    if leaves_route(upstream_path):
        raise HTTPException(status_code=403, detail="Eneo resource is not exposed")
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


class _SignedUrl(NamedTuple):
    url: str
    expires_at: float


# The cache is request.app.state.signed_urls, made by create_app.
# Keyed by session and the Eneo path that mints the URL: one URL per file.


def _rebase_signed_url(signed_url: str, base_url: str) -> str:
    """Point a signed URL at the Eneo host the module backend can reach.

    Eneo builds signed URLs on its public base URL; on the module network the
    backend reaches Eneo on ``ENEO_BACKEND_URL`` instead. Only scheme and host
    change — the path and the signed query survive untouched.
    """
    signed = urlsplit(signed_url)
    base = urlsplit(base_url)
    return urlunsplit((base.scheme, base.netloc, signed.path, signed.query, ""))


def _prune_signed_urls(signed_urls: dict[tuple[str, str], _SignedUrl], now: float) -> None:
    for key, entry in list(signed_urls.items()):
        if entry.expires_at <= now:
            signed_urls.pop(key, None)


async def _signed_url(request: Request, key: tuple[str, str], unavailable: str) -> str:
    settings = request.app.state.settings
    http_client = request.app.state.http
    signed_urls = request.app.state.signed_urls
    now = time.time()
    cached = signed_urls.get(key)
    if cached and cached.expires_at - _SIGNED_URL_REFRESH_MARGIN_SECONDS > now:
        return cached.url

    mint_path = key[1]
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

    payload = upstream.json()
    url = _rebase_signed_url(str(payload["url"]), settings.eneo_backend_url)
    expires_at = float(payload.get("expires_at") or now + _SIGNED_URL_TTL_SECONDS)
    _prune_signed_urls(signed_urls, now)
    signed_urls[key] = _SignedUrl(url=url, expires_at=expires_at)
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
    signed_urls = request.app.state.signed_urls
    if any(leaves_route(part) for part in resource):
        raise HTTPException(status_code=403, detail="Eneo resource is not exposed")

    key = (request.cookies.get(SESSION_COOKIE) or "", mint_path)
    url = await _signed_url(request, key, unavailable)

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

    if upstream.status_code >= 400:
        # A rejected token is not worth keeping around; the next request mints anew.
        signed_urls.pop(key, None)
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
