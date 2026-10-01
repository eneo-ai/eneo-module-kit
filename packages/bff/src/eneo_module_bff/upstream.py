"""The one HTTP client a module uses to reach Eneo, and how it is built."""

from __future__ import annotations

from http.cookiejar import Cookie, CookieJar, CookiePolicy
from urllib.request import Request

import httpx2


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


def make_client(*, transport: httpx2.AsyncBaseTransport | None = None) -> httpx2.AsyncClient:
    """The client ``create_app`` builds when it is not given one; ``transport`` is for tests.

    One client serves every user, and every call carries the service key. A cookie Eneo sets on one user's call
    would be stored in the client's jar and sent with the next user's, so this client keeps none: every call to
    Eneo is authorised by its headers alone. A module that passes its own client owns that policy.
    """
    return httpx2.AsyncClient(
        # pool=5: a call waits at most 5 s for a free connection. With the default 60 s, a pool held full by
        # streams made every API call a 502 after a minute.
        timeout=httpx2.Timeout(60.0, connect=10.0, pool=5.0),
        follow_redirects=False,
        cookies=CookieJar(policy=_NoCookies()),
        transport=transport,
    )
