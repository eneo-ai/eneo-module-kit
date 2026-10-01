"""What only a real HTTP parser shows: uvicorn's httptools and h11 treat the same bytes differently."""

import socket
import unittest

from . import real_server

APP = """
from fastapi import APIRouter, Request
from eneo_module_bff import Settings, create_app, serve

router = APIRouter()


@router.post("/api/public")
async def public(request: Request):
    return {"n": len(await request.body())}


settings = Settings(
    eneo_backend_url="http://127.0.0.1:1", eneo_public_url="http://eneo.example", module_public_url="http://127.0.0.1:PORT",
    module_key="real", eneo_api_key="K", session_secret="x" * 48, cookie_secure=False,
)
serve(create_app(settings, routers=[router]), host="127.0.0.1", port=PORT, http="HTTP")
"""


def status_of(port: int, content_length: str, body: bytes = b"hello") -> str:
    request = f"POST /api/public HTTP/1.1\r\nHost: x\r\nContent-Length: {content_length}\r\nConnection: close\r\n\r\n".encode() + body
    with socket.create_connection(("127.0.0.1", port), timeout=10) as connection:
        connection.sendall(request)
        reply = b""
        while b"\r\n" not in reply:
            chunk = connection.recv(4096)
            if not chunk:
                break
            reply += chunk
    return reply.split(b"\r\n")[0].decode()


class ContentLengthTests(unittest.TestCase):
    def test_a_malformed_or_overlong_content_length_is_a_400_never_a_500_on_both_parsers(self) -> None:
        for parser in ("httptools", "h11"):
            process, port = real_server.start(self, APP.replace("HTTP", parser))
            with self.subTest(parser=parser):
                self.assertEqual(status_of(port, "5"), "HTTP/1.1 200 OK", "a good length still works")
                for value in ("0" * 5000 + "5", "9" * 5001, "0" * 4300 + "5", "0" * 4301 + "5", "9" * 25, "9223372036854775808"):
                    self.assertTrue(status_of(port, value).startswith("HTTP/1.1 400"), f"{parser}: {value[:12]}... ({len(value)} digits)")


if __name__ == "__main__":
    unittest.main()
