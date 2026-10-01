"""The one HTTP client a module uses to reach Eneo, and how it is built."""

from __future__ import annotations

from collections.abc import AsyncIterator
from http.cookiejar import Cookie, CookieJar, CookiePolicy
from urllib.request import Request

import httpx2

from .settings import Settings

# The request extension that sets how much of that request's answer is read: a number of bytes, or None for none (a
# file that streams). A request without it gets ``Settings.max_response_bytes``.
LIMIT = "eneo_module_bff.max_response_bytes"
# For the answers that carry a token or a URL, and the body of a failed file answer: a few lines of JSON, never more.
SMALL_ANSWER_BYTES = 1024 * 1024
SMALL_ANSWER = {LIMIT: SMALL_ANSWER_BYTES}
STREAMED = {LIMIT: None}


class UnboundedAnswer(httpx2.TransportError):
    """An answer whose size the module will not read: past its bound, or encoded, so that its decoded size is not known."""


class _NoCookies(CookiePolicy):
    """Stores no cookie and sends none."""

    netscape = True
    rfc2965 = False
    hide_cookie2 = False

    def set_ok(self, cookie: Cookie, request: Request) -> bool:
        return False

    def return_ok(self, cookie: Cookie, request: Request) -> bool:
        return False

    def domain_return_ok(self, domain: str, request: Request) -> bool:
        return False

    def path_return_ok(self, path: str, request: Request) -> bool:
        return False


class _Counted(httpx2.AsyncByteStream):
    """The body of an answer, until it has passed ``limit`` bytes."""

    def __init__(self, stream: httpx2.AsyncByteStream, limit: int, request: httpx2.Request) -> None:
        self._stream, self._limit, self._request, self._seen = stream, limit, request, 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for chunk in self._stream:
            self._seen += len(chunk)
            if self._seen > self._limit:
                raise UnboundedAnswer(f"The answer is longer than {self._limit} bytes", request=self._request)
            yield chunk

    async def aclose(self) -> None:
        await self._stream.aclose()


def make_client(settings: Settings, *, transport: httpx2.AsyncBaseTransport | None = None) -> httpx2.AsyncClient:
    """The client ``create_app`` builds when it is not given one; ``transport`` is for tests.

    One client serves every user, and every call carries the service key. A cookie Eneo sets on one user's call
    would be stored in the client's jar and sent with the next user's, so this client keeps none: every call to
    Eneo is authorised by its headers alone.

    No answer is read past a bound (``Settings.max_response_bytes``, or the request's own ``LIMIT``), counted while
    it arrives, and the answer is closed past it: ``UnboundedAnswer``, a ``RequestError``. The module asks for no
    encoding and refuses an encoded answer, so what is counted is what would be held (a few KB of gzip can decode to
    gigabytes). A request with ``LIMIT`` None is a file that streams.

    A module that passes its own client to ``create_app`` owns all of this.
    """

    async def bound(response: httpx2.Response) -> None:
        request = response.request
        limit = request.extensions.get(LIMIT, settings.max_response_bytes)
        if limit is None:
            return
        if response.headers.get("content-encoding", "identity").strip().lower() not in {"", "identity"}:
            raise UnboundedAnswer("The answer is encoded, and its decoded size is not known", request=request)
        declared = response.headers.get("content-length", "")
        if declared.isascii() and declared.isdigit() and (len(declared) > 18 or int(declared) > limit):
            raise UnboundedAnswer(f"The answer declares {declared} bytes, more than {limit}", request=request)
        response.stream = _Counted(response.stream, limit, request)

    return httpx2.AsyncClient(
        # pool=5: a call waits at most 5 s for a free connection. With the default 60 s, a pool held full by
        # streams made every API call a 502 after a minute.
        timeout=httpx2.Timeout(60.0, connect=10.0, pool=5.0),
        follow_redirects=False,
        cookies=CookieJar(policy=_NoCookies()),
        headers={"Accept-Encoding": "identity"},
        event_hooks={"response": [bound]},
        transport=transport,
    )
