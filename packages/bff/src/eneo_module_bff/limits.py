"""How much of a request body the module reads.

No body is read before the module's own dependencies have run, and none past a limit. One pure-ASGI middleware
holds it for the whole app, whatever route or content type:

- Every request body is capped at ``max_body_bytes``: 413 at once if its length is declared above the cap, and 413
  as soon as the stream passes it. It looks at no session, so it holds for a module's deliberately public routes too,
  and it answers before FastAPI parses a JSON body into a model (FastAPI does that before it runs a route's
  dependencies, and reads a body whatever the content type says: a content type is the client's claim, so none is
  exempt).
- ``forward_upload`` raises the limit to ``max_upload_bytes`` for its own request, after the route's dependencies
  have run and its own length checks have passed. The count is of the bytes that arrive, so a Content-Length that
  lies, or a chunked body, gets no further.
"""

from __future__ import annotations

from fastapi import HTTPException, Request
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

TOO_LARGE = "Request body too large"
# The scope key that holds this request's limit, once the code that handles an upload has raised it.
BODY_LIMIT = "eneo_module_bff.body_limit"


def too_large(detail: str = TOO_LARGE) -> HTTPException:
    # Connection: close, so that a client that is still sending stops.
    return HTTPException(status_code=413, detail=detail, headers={"Connection": "close"})


def declared_length(headers: Headers) -> int | None:
    """The Content-Length a request declares, or None if it has none or it is not a number."""
    value = headers.get("content-length")
    return int(value) if value is not None and value.isascii() and value.isdigit() else None


def allow_upload(request: Request, limit: int) -> None:
    """Let this request's body be ``limit`` bytes (not the default): called by the code that reads an upload."""
    request.scope[BODY_LIMIT] = limit


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_body_bytes: int, max_upload_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.max_upload_bytes = max_upload_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        # A length above this is refused whatever route it is for: only a multipart upload may be as big as an
        # upload, and a body that claims to be one still has to get through the count below.
        multipart = headers.get("content-type", "").lower().startswith("multipart/form-data")
        ceiling = self.max_upload_bytes if multipart else self.max_body_bytes
        declared = declared_length(headers)
        if declared is not None and declared > ceiling:
            error = too_large()
            await JSONResponse({"detail": error.detail}, status_code=413, headers=error.headers)(scope, receive, send)
            return
        received = 0

        async def counted_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > scope.get(BODY_LIMIT, self.max_body_bytes):
                    # An HTTPException, not a private error: FastAPI turns any other exception raised while it
                    # reads a body into a 400.
                    raise too_large()
            return message

        await self.app(scope, counted_receive, send)
