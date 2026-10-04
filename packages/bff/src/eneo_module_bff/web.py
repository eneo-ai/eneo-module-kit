import os
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response

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


# An answer of the app is one user's: no cache keeps it. The default of every answer under /api, and the proxy's and
# the file streams' own.
NO_STORE = "private, no-store"


def add_security_headers(app: FastAPI, overrides: dict[str, str] | None = None) -> None:
    """Every response gets the headers unless the route set its own (a same-origin PDF preview, a logo). An answer
    under ``/api`` that says nothing about caching is ``NO_STORE``."""
    headers = {**SECURITY_HEADERS, **(overrides or {})}

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response: Response = await call_next(request)
        for name, value in headers.items():
            response.headers.setdefault(name, value)
        path = request.scope["path"]
        if path == "/api" or path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", NO_STORE)
        return response


# The built UI's hashed files live here, and a name under it that is gone is a 404, never the page.
ASSETS = "assets"
# A path with one of these (NUL and the rest of C0, DEL, a backslash), or a segment that starts with a dot (a dotfile, "."
# and ".."), names nothing: a 404, never the page, a file or a way past the /api rule.
_NOT_A_NAME = re.compile(r"[\x00-\x1f\x7f\\]|(?:^|/)\.")
# A compressed sibling of a file is for whoever negotiates it, never reached by its own name.
_COMPRESSED = (".br", ".gz")


def _built_files(root: Path) -> dict[str, Path]:
    """The files of the built UI by the path each is served at, read once: not the page, not a dotfile, not a compressed
    sibling, and none that a link leads out of ``root``."""
    files: dict[str, Path] = {}
    for folder, _, names in os.walk(root):
        for name in names:
            candidate = Path(folder, name)
            served = candidate.relative_to(root).as_posix()
            if served == "index.html" or served.lower().endswith(_COMPRESSED) or _NOT_A_NAME.search(served):
                continue
            real = candidate.resolve()
            if root in real.parents and real.is_file():
                files[served] = real
    return files


def serve_web(app: FastAPI, static_dir: Path) -> None:
    """The built UI: its files, and its one HTML file for every page of the app.

    Registered last. The folder is read once, here: a request is a lookup, with no path resolved and no disk asked to
    find a file. ``/api`` and anything under it that no route answered is a 404 JSON, and so is a path that names a
    file that is not there, a path no file or page has a name like (a control character, a backslash, a dot segment, a
    dotfile), and a second URL of a file (``/assets/app.js/``); never HTML. HEAD is answered as GET is.
    """
    root = static_dir.resolve()
    index = root / "index.html"
    has_page = index.is_file()  # a folder with no index.html answers no page
    files = _built_files(root)
    page_headers = {"Cache-Control": "no-cache"}

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def page(path: str, request: Request) -> Response:
        # The scope's path, not ``path``: the route's pattern drops one leading slash (``//api/x`` is ``/api/x``) and, ending
        # in ``$``, a trailing newline.
        asked = request.scope["path"]
        if _NOT_A_NAME.search(asked) or asked.lstrip("/") == "api" or asked.lstrip("/").startswith("api/"):
            raise HTTPException(status_code=404)
        last = path.rsplit("/", 1)[-1]
        if path == "index.html" or (not path.startswith(f"{ASSETS}/") and "." not in last):
            if not has_page:
                raise HTTPException(status_code=404)
            return FileResponse(index, headers=page_headers)
        file = files.get(path)
        if file is None:
            raise HTTPException(status_code=404)
        return FileResponse(file)
