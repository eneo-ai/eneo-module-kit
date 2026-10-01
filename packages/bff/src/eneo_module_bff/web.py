from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

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


def serve_web(app: FastAPI, static_dir: Path) -> None:
    """The built UI: its assets, and its one HTML file for every page of the app.

    Registered last. A path under /api, and a path that names a file that is not there, is a 404, never HTML.
    """
    root = static_dir.resolve()
    app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def page(path: str) -> Response:
        if path.startswith("api/"):
            raise HTTPException(status_code=404)
        if "." in path.rsplit("/", 1)[-1]:
            candidate = (root / path).resolve()
            if candidate.is_file() and root in candidate.parents:
                return FileResponse(candidate)
            raise HTTPException(status_code=404)
        return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})
