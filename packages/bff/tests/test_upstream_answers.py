"""How much of an answer from Eneo the module reads: a bound, checked while it arrives, and the answer closed past it.

Eneo here is an ``httpx2`` transport that serves a body lazily and counts what was taken from it, so no oversized
answer exists in memory in these tests.
"""

import gzip
import json
import unittest

import httpx2
from fastapi import APIRouter, Depends, Request

from eneo_module_bff.deps import require_same_origin, require_session
from eneo_module_bff.proxy import RESOURCE_ID, rule
from eneo_module_bff.transport import forward_upload, stream_signed

from .fake_eneo import Module

MiB = 1 << 20
CAP = 4 * MiB  # max_response_bytes in these tests
RULES = (rule("GET", rf"things/{RESOURCE_ID}/$"),)
MINT = json.dumps({"url": "http://eneo.example/signed/f1?sig=1"}).encode()

router = APIRouter()


@router.post("/upload/f1", dependencies=[Depends(require_session), Depends(require_same_origin)])
async def upload(request: Request):
    return await forward_upload(request, "flows/f1/files/")


@router.get("/files/f1", dependencies=[Depends(require_session)])
async def download(request: Request):
    return await stream_signed(request, "f1", mint_path="files/f1/signed-url/", unavailable="no file")


class Lazy(httpx2.AsyncByteStream):
    """``total`` bytes served a MiB at a time, never held, and what was taken and whether it was closed."""

    def __init__(self, total: int, chunk: bytes = b"0" * MiB) -> None:
        self.total, self.chunk, self.sent, self.closed = total, chunk, 0, False

    async def __aiter__(self):
        while self.sent < self.total:
            piece = self.chunk[: self.total - self.sent]
            self.sent += len(piece)
            yield piece

    async def aclose(self) -> None:
        self.closed = True


class Eneo(httpx2.AsyncBaseTransport):
    """Answers per request by ``respond(request)``, a (status, headers, body stream or bytes) triple."""

    def __init__(self, respond) -> None:
        self.respond, self.streams = respond, []

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        status, headers, body = self.respond(request)
        if isinstance(body, bytes):
            return httpx2.Response(status, headers=headers, content=body)
        self.streams.append(body)
        return httpx2.Response(status, headers=headers, stream=body)


def json_headers(**more: str) -> dict[str, str]:
    return {"content-type": "application/json", **more}


class ProxyAnswerTests(unittest.IsolatedAsyncioTestCase):
    def module(self, respond) -> tuple[Eneo, object]:
        eneo = Eneo(respond)
        return eneo, Module(self, transport=eneo, proxy_rules=RULES, routers=(router,), max_response_bytes=CAP).browser()

    async def test_an_answer_past_the_bound_is_a_502_that_stops_reading_and_closes_it(self) -> None:
        eneo, browser = self.module(lambda request: (200, json_headers(), Lazy(300 * MiB)))

        response = await browser.get("/api/eneo/things/x/")

        self.assertEqual((response.status_code, response.json()["error"]), (502, "upstream_too_large"))
        self.assertLessEqual(eneo.streams[0].sent, CAP + MiB)
        self.assertTrue(eneo.streams[0].closed)

    async def test_a_declared_length_past_the_bound_is_refused_before_a_byte_is_read(self) -> None:
        eneo, browser = self.module(lambda request: (200, json_headers(**{"content-length": str(10**9)}), Lazy(300 * MiB)))

        response = await browser.get("/api/eneo/things/x/")

        self.assertEqual((response.status_code, response.json()["error"]), (502, "upstream_too_large"))
        self.assertEqual(eneo.streams[0].sent, 0)
        self.assertTrue(eneo.streams[0].closed)

    async def test_a_compressed_answer_is_refused_whatever_it_would_decode_to(self) -> None:
        bomb = gzip.compress(b"0" * (64 * MiB), 1)  # about 64 KB that decode to 64 MiB
        eneo, browser = self.module(lambda request: (200, json_headers(**{"content-encoding": "gzip"}), Lazy(len(bomb), bomb)))

        response = await browser.get("/api/eneo/things/x/")

        self.assertEqual((response.status_code, response.json()["error"]), (502, "upstream_too_large"))
        self.assertEqual(eneo.streams[0].sent, 0)
        self.assertTrue(eneo.streams[0].closed)

    async def test_an_answer_at_the_bound_goes_through(self) -> None:
        eneo, browser = self.module(lambda request: (200, {"content-type": "application/octet-stream"}, Lazy(CAP)))

        response = await browser.get("/api/eneo/things/x/")

        self.assertEqual((response.status_code, len(response.content)), (200, CAP))

    async def test_the_client_asks_for_no_encoding(self) -> None:
        seen = []
        eneo, browser = self.module(lambda request: (seen.append(request.headers["accept-encoding"]) or 200, json_headers(), b"{}"))

        await browser.get("/api/eneo/things/x/")

        self.assertEqual(seen, ["identity"])


class ControlAnswerTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_signed_url_answer_past_a_small_bound_is_invalid_and_not_read_on(self) -> None:
        eneo = Eneo(lambda request: (200, json_headers(), Lazy(300 * MiB)))
        browser = Module(self, transport=eneo, routers=(router,), max_response_bytes=64 * MiB).browser()

        response = await browser.get("/files/f1")

        self.assertEqual((response.status_code, response.json()["error"]), (502, "upstream_invalid"))
        self.assertLessEqual(eneo.streams[0].sent, 2 * MiB)
        self.assertTrue(eneo.streams[0].closed)

    async def test_the_body_of_a_failed_file_answer_is_read_to_a_small_bound_and_closed(self) -> None:
        def respond(request):
            if request.url.path.endswith("/signed-url/"):
                return 200, json_headers(), MINT
            return 500, json_headers(), Lazy(300 * MiB)

        eneo = Eneo(respond)
        browser = Module(self, transport=eneo, routers=(router,), max_response_bytes=64 * MiB).browser()

        response = await browser.get("/files/f1")

        self.assertEqual(response.status_code, 500)
        self.assertLessEqual(eneo.streams[0].sent, 2 * MiB)
        self.assertTrue(eneo.streams[0].closed)

    async def test_an_upload_answer_past_the_bound_is_a_502(self) -> None:
        eneo = Eneo(lambda request: (200, json_headers(), Lazy(300 * MiB)))
        browser = Module(self, transport=eneo, routers=(router,), max_response_bytes=CAP).browser()

        response = await browser.post("/upload/f1", files={"upload_file": ("a.bin", b"x", "application/octet-stream")})

        self.assertEqual((response.status_code, response.json()["error"]), (502, "upstream_too_large"))
        self.assertTrue(eneo.streams[0].closed)

    async def test_a_ticket_exchange_answer_past_a_small_bound_ends_the_login_without_a_session(self) -> None:
        eneo = Eneo(lambda request: (200, json_headers(), Lazy(300 * MiB)))
        module = Module(self, transport=eneo, max_response_bytes=64 * MiB)
        browser = module.browser(signed_in=False)
        login = await browser.get("/api/auth/login")
        state = httpx2.URL(login.headers["location"]).params["state"]

        response = await browser.get("/api/auth/callback", params={"ticket": "t", "state": state})

        self.assertEqual(response.headers["location"], "/?auth_error=exchange_unavailable")
        self.assertLessEqual(eneo.streams[0].sent, 2 * MiB)
        self.assertTrue(eneo.streams[0].closed)


if __name__ == "__main__":
    unittest.main()
