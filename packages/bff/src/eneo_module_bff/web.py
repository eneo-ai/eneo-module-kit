import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
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


class _Assets(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        if _NOT_A_NAME.search(scope["path"]):
            raise HTTPException(status_code=404)
        return await super().get_response(path, scope)


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


def serve_web(app: FastAPI, static_dir: Path) -> None:
    """The built UI: its assets, and its one HTML file for every page of the app.

    Registered last. /api and a path under it, a path that names a file that is not there, and a path that names
    nothing (``_NOT_A_NAME``) are a 404, never HTML and never a 500.
    """
    root = static_dir.resolve()
    app.mount("/assets", _Assets(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def page(path: str, request: Request) -> Response:
        # The scope's path, not ``path``: the route's pattern drops one leading slash (``//api/x`` is ``/api/x``) and,
        # ending in ``$``, a trailing newline.
        asked = request.scope["path"].lstrip("/")
        if _NOT_A_NAME.search(asked) or asked == "api" or asked.startswith("api/"):
            raise HTTPException(status_code=404)
        if "." in path.rsplit("/", 1)[-1]:
            if (candidate := _file_under(root, path)) is not None:
                return FileResponse(candidate)
            raise HTTPException(status_code=404)
        return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})
