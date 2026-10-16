import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

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


def add_security_headers(app: FastAPI, overrides: dict[str, str] | None = None) -> None:
    """Every response gets the headers unless the route set its own (a same-origin PDF preview, a logo)."""
    headers = {**SECURITY_HEADERS, **(overrides or {})}

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response: Response = await call_next(request)
        for name, value in headers.items():
            response.headers.setdefault(name, value)
        return response


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
