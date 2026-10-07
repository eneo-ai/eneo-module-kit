"""How much of a request body the module reads.

No body is read before the module's own dependencies have run, and none past a limit. One pure-ASGI middleware
holds it for the whole app, whatever route or content type:

- A Content-Length that is not a length (not digits, or too long to be one) is a 400 before anything is read.
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

from collections.abc import Iterator
from contextlib import contextmanager

import anyio
from fastapi import HTTPException, Request
from starlette.requests import HTTPConnection
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

TOO_LARGE = "Request body too large"
INVALID_LENGTH = "Invalid Content-Length"
# The longest Content-Length that can be a length (2**63 - 1 has 19 digits): a longer one is refused unparsed.
MAX_LENGTH_DIGITS = 19
# The scope key that holds this request's limit, once the code that handles an upload has raised it.
BODY_LIMIT = "eneo_module_bff.body_limit"


@contextmanager
def _capacity_slot(limiter: anyio.CapacityLimiter) -> Iterator[bool]:
    """Try admission without queueing, and hold capacity until the caller's cleanup finishes."""
    borrower = object()
    try:
        limiter.acquire_on_behalf_of_nowait(borrower)
    except anyio.WouldBlock:
        yield False
        return
    try:
        yield True
    finally:
        limiter.release_on_behalf_of(borrower)


@contextmanager
def heavy_io_slot(connection: HTTPConnection) -> Iterator[bool]:
    """One heavy operation, sharing admission with uploads and signed files.

    ``with heavy_io_slot(request_or_websocket) as admitted`` never waits. If false,
    the module returns its own retryable overload response before reading a body
    or opening an upstream connection. If true, keep the context through cleanup.
    A module holding multiple upstream connections takes one slot for each.
    """
    with _capacity_slot(connection.app.state.heavy_io_slots) as admitted:
        yield admitted


def too_large(detail: str = TOO_LARGE) -> HTTPException:
    # Connection: close, so that a client that is still sending stops.
    return HTTPException(status_code=413, detail=detail, headers={"Connection": "close"})


def invalid_length() -> HTTPException:
    return HTTPException(status_code=400, detail=INVALID_LENGTH, headers={"Connection": "close"})


def declared_length(headers: Headers) -> int | None:
    """The Content-Length a request declares, or None if it has none.

    A header that is there but is not a length (not ASCII digits, longer than 19 characters, or 2**63 or more) is a
    400. The length is checked before it is parsed: int() refuses a string of more than 4300 digits, and uvicorn's
    httptools parser lets a zero-padded one of any length through, so parsing it first would be a 500.
    """
    value = headers.get("content-length")
    if value is None:
        return None
    if len(value) > MAX_LENGTH_DIGITS or not (value.isascii() and value.isdigit()) or int(value) >= 2**63:
        raise invalid_length()
    return int(value)


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
        try:
            declared = declared_length(headers)
        except HTTPException as error:
            await JSONResponse({"detail": error.detail}, status_code=error.status_code, headers=error.headers)(scope, receive, send)
            return
        if declared is not None and declared > ceiling:
            error = too_large()
            await JSONResponse({"detail": error.detail}, status_code=413, headers=error.headers)(scope, receive, send)
            return
        received = 0
        answering = False
        overflowed = False

        async def tracked_send(message: Message) -> None:
            nonlocal answering
            if message["type"] == "http.response.start":
                answering = True
            await send(message)

        async def counted_receive() -> Message:
            nonlocal received, overflowed
            if overflowed:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > scope.get(BODY_LIMIT, self.max_body_bytes):
                    if answering:
                        # A response is already on its way (a stream that never asked for the body, whose server
                        # side only listens here for the client to go): the client is as good as gone, and a 413
                        # can no longer be sent.
                        overflowed = True
                        return {"type": "http.disconnect"}
                    # An HTTPException, not a private error: FastAPI turns any other exception raised while it
                    # reads a body into a 400.
                    raise too_large()
            return message

        await self.app(scope, counted_receive, tracked_send)
