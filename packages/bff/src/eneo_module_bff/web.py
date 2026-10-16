import re
from mimetypes import guess_type
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data: blob:",
        "media-src 'self' blob:",
        "font-src 'self'",
        "connect-src 'self'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "object-src 'none'",
    ]
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
}


NO_STORE = (b"cache-control", b"no-store")


class SecurityHeadersMiddleware:
    """Adds each of ``headers`` that an HTTP answer lacks, a streamed one and an error too. An answer under ``/api``
    also gets ``Cache-Control: no-store`` if it says nothing about caching: one user's data must not land in a shared
    computer's disk cache. A route that sets its own (a same-origin PDF preview, the logo, the theme) keeps it.

    Pure ASGI: the answer is passed on as it is built, so a streamed body is not wrapped, and a client that leaves ends
    the stream where it always did.
    """

    def __init__(self, app: ASGIApp, headers: dict[str, str]) -> None:
        self.app = app
        self.headers = [(name.lower().encode("latin-1"), value.encode("latin-1")) for name, value in headers.items()]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        api = scope["path"] == "/api" or scope["path"].startswith("/api/")
        added = [*self.headers, NO_STORE] if api else self.headers

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                present = {name.lower() for name, _ in message.get("headers", [])}
                message = {**message, "headers": [*message.get("headers", []), *(h for h in added if h[0] not in present)]}
            await send(message)

        await self.app(scope, receive, send_with_headers)


def add_security_headers(app: FastAPI, overrides: dict[str, str] | None = None) -> None:
    """The headers on every answer of ``app``, ``overrides`` replacing defaults by name. Add it after the other
    middleware: the one added last is the outermost, and every answer the others give (a 413) must carry them."""
    headers = {**SECURITY_HEADERS, **(overrides or {})}
    app.add_middleware(SecurityHeadersMiddleware, headers=headers)

    async def internal_server_error(request: Request, error: Exception) -> PlainTextResponse:
        # What Starlette sends for an unhandled exception, with the headers: it answers outside every middleware. The
        # exception is still raised after it, so the server logs it.
        return PlainTextResponse("Internal Server Error", status_code=500, headers={**headers, "Cache-Control": "no-store"})

    app.add_exception_handler(Exception, internal_server_error)


# A path with one of these (NUL and the rest of C0, DEL, a backslash), or a segment that starts with a dot (a dotfile,
# "." and ".."), names nothing: a 404, never the page, a file or a way past the /api rule.
_NOT_A_NAME = re.compile(r"[\x00-\x1f\x7f\\]|(?:^|/)\.")

# Under assets/ the build names every file by its content, so a new build has new names: such a file is kept for a year
# and never asked for again. Everything else keeps its name (the page, the files beside it) and is asked for every time.
ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"
# A .br and a .gz the build writes beside a file (template/web/vite.config.ts), in the order a client that accepts both
# is sent them. Never served by their own names.
ENCODINGS = (("br", ".br"), ("gzip", ".gz"))
_COMPRESSED = tuple(suffix for _, suffix in ENCODINGS)


def etag_matches(if_none_match: str | None, current: str) -> bool:
    """Whether the client already holds the body ``current`` names (a weak comparison, as for a GET)."""
    if if_none_match is None:
        return False
    listed = {value.strip().removeprefix("W/") for value in if_none_match.split(",")}
    return "*" in listed or current in listed


def accepted_encodings(accept_encoding: str | None) -> set[str]:
    """The content codings a client names with a quality above zero (``gzip``; ``br;q=0`` is not one)."""
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


def _file_under(root: Path, relative: str) -> Path | None:
    """The file ``relative`` names inside ``root``, or None: for a link or a ``..`` that leaves ``root``, a name the
    system refuses (too long), and anything that is not a file. Never an exception."""
    try:
        candidate = (root / relative).resolve()
        if root in candidate.parents and candidate.is_file():
            return candidate
    except (OSError, ValueError, RuntimeError):
        pass
    return None


def _file_response(request: Request, root: Path, relative: str, cache_control: str) -> Response:
    """The file ``relative`` names inside ``root`` (``_file_under``), or a 404: a precompressed sibling of it to a client
    that accepts one, the ETag of the body that goes out (FileResponse's), and a 304 when the client holds that body."""
    if (file := _file_under(root, relative)) is None:
        raise HTTPException(status_code=404)
    headers = {"Cache-Control": cache_control}
    body = file
    siblings = [(coding, _file_under(root, relative + suffix)) for coding, suffix in ENCODINGS]
    if present := [(coding, sibling) for coding, sibling in siblings if sibling is not None]:
        headers["Vary"] = "Accept-Encoding"
        accepted = accepted_encodings(request.headers.get("accept-encoding"))
        for coding, sibling in present:
            if coding in accepted:
                body, headers["Content-Encoding"] = sibling, coding
                break
    response = FileResponse(body, headers=headers, media_type=guess_type(file.name)[0], stat_result=body.stat())
    if etag_matches(request.headers.get("if-none-match"), response.headers["etag"]):
        kept = ("cache-control", "etag", "vary")
        return Response(status_code=304, headers={name: response.headers[name] for name in kept if name in response.headers})
    return response


def serve_web(app: FastAPI, static_dir: Path) -> None:
    """The built UI: its files, and its one HTML file for every page of the app.

    Registered last. /api and a path under it, a path under /assets or with a dot in its last segment that names no file,
    a compressed sibling asked for by its name, and a path that names nothing (``_NOT_A_NAME``) are a 404, never HTML and
    never a 500.
    """
    root = static_dir.resolve()

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def page(path: str, request: Request) -> Response:
        # The scope's path, not ``path``: the route's pattern drops one leading slash (``//api/x`` is ``/api/x``) and,
        # ending in ``$``, a trailing newline.
        asked = request.scope["path"].lstrip("/")
        if _NOT_A_NAME.search(asked) or asked == "api" or asked.startswith("api/") or asked.endswith(_COMPRESSED):
            raise HTTPException(status_code=404)
        hashed = path.startswith("assets/")
        if hashed or "." in path.rsplit("/", 1)[-1]:
            return _file_response(request, root, path, ASSET_CACHE_CONTROL if hashed else REVALIDATE)
        return _file_response(request, root, "index.html", REVALIDATE)
