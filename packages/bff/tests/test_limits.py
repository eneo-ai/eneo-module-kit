"""Request bodies: capped, and never read before a module's own dependencies have run.

A body is fed to the app lazily, one MiB at a time, and the test counts how many pieces the app took before it
answered. Nothing here materialises a large body.
"""

import os
import tempfile
import time
import unittest

import httpx2
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from eneo_module_bff.app import create_app
from eneo_module_bff.auth import SESSION_COOKIE, ModuleSession, ModuleUser
from eneo_module_bff.deps import require_same_origin, require_session
from eneo_module_bff.proxy import rule
from eneo_module_bff.settings import Settings
from eneo_module_bff.transport import forward_upload

MiB = 1 << 20
BOUNDARY = "limitsboundary"
ORIGIN = "http://module.example.test"
CAP = 4 * MiB  # max_body_bytes in these tests
UPLOAD_CAP = 8 * MiB  # max_upload_bytes in these tests


class Thing(BaseModel):
    text: str


class Eneo:
    """Eneo as the module's client sees it: records what it was sent, and reads an uploaded file to its end."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def request(self, **kwargs):
        self.calls.append(kwargs)
        return Answer()

    async def post(self, url, **kwargs):
        file = kwargs["files"]["upload_file"]
        self.calls.append({"url": url, "filename": file[0], "content_type": file[2], "size": len(file[1].read())})
        return Answer()


class Answer:
    content = b'{"ok":true}'
    status_code = 200
    headers = {"content-type": "application/json"}


class Lazy:
    """A request body of ``total`` MiB that never exists in memory, and how many MiB of it were taken."""

    def __init__(self, total_mib: int, head: bytes = b"", tail: bytes = b"") -> None:
        self.total_mib, self.head, self.tail, self.taken = total_mib, head, tail, 0

    @property
    def length(self) -> int:
        return len(self.head) + self.total_mib * MiB + len(self.tail)

    async def stream(self):
        if self.head:
            yield self.head
        for _ in range(self.total_mib):
            self.taken += 1
            yield b"0" * MiB
        if self.tail:
            yield self.tail


def multipart_head(name: str = "upload_file", filename: str = "a.bin", content_type: str = "application/octet-stream") -> bytes:
    return (
        f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode()


MULTIPART_TAIL = f"\r\n--{BOUNDARY}--\r\n".encode()
MULTIPART = {"Content-Type": f"multipart/form-data; boundary={BOUNDARY}", "Origin": ORIGIN}


def multipart_of(total_mib: int) -> Lazy:
    return Lazy(total_mib, multipart_head(), MULTIPART_TAIL)


def session() -> ModuleSession:
    now = int(time.time())
    return ModuleSession(
        access_token="module-user-token", expires_at=now + 600, refresh_at=now + 300, session_expires_at=now + 3600,
        module_key="limits", tenant_id="t", user=ModuleUser(id="u", email="u@example.test"),
    )


def build() -> tuple:
    """A module: a guarded JSON route, a deliberately public JSON route, a guarded upload route, one proxy rule."""
    eneo = Eneo()
    settings = Settings(
        eneo_backend_url="http://eneo.test", eneo_public_url="http://eneo.example", module_public_url=ORIGIN,
        module_key="limits", eneo_api_key="K", session_secret="x" * 48, cookie_secure=False,
        max_body_bytes=CAP, max_upload_bytes=UPLOAD_CAP,
    )
    router = APIRouter()

    @router.post("/api/things", dependencies=[Depends(require_session)])
    async def create(thing: Thing) -> dict[str, int]:
        return {"length": len(thing.text)}

    @router.post("/api/public")
    async def public(thing: Thing) -> dict[str, int]:
        return {"length": len(thing.text)}

    @router.post("/upload/{flow_id}", dependencies=[Depends(require_session), Depends(require_same_origin)])
    async def upload(flow_id: str, request: Request):
        return await forward_upload(request, f"flows/{flow_id}/files/")

    app = create_app(settings, routers=[router], proxy_rules=[rule("POST", r"things/$")], http_client=eneo)
    return app, eneo, app.state.module_auth.sessions.create(session())


def client(app, session_id: str | None = None) -> httpx2.AsyncClient:
    c = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=ORIGIN)
    if session_id:
        c.cookies.set(SESSION_COOKIE, session_id)
    return c


class Case(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.app, self.eneo, self.session_id = build()

    async def post(self, path: str, body: Lazy, *, authenticated: bool = True, declare_length: bool = True, headers: dict | None = None):
        sent = {"Content-Type": "application/json", **(headers or {})}
        if declare_length:
            sent["Content-Length"] = str(body.length)
        async with client(self.app, self.session_id if authenticated else None) as c:
            return await c.post(path, content=body.stream(), headers=sent)


class JsonBodyTests(Case):
    async def test_a_body_over_the_cap_with_a_declared_length_is_413_and_never_read(self) -> None:
        body = Lazy(400)

        response = await self.post("/api/things", body)

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json(), {"detail": "Request body too large"})
        self.assertEqual(response.headers["connection"], "close")
        self.assertEqual(body.taken, 0)

    async def test_a_chunked_body_is_counted_while_it_streams_and_stops_at_the_cap(self) -> None:
        body = Lazy(400)

        response = await self.post("/api/things", body, declare_length=False)

        self.assertEqual(response.status_code, 413)
        self.assertLessEqual(body.taken, CAP // MiB + 2, "the rest of 400 MiB was never taken")

    async def test_the_cap_needs_no_session_and_comes_before_the_route_looks_at_the_body(self) -> None:
        for authenticated in (False, True):
            with self.subTest(authenticated=authenticated):
                body = Lazy(400)

                response = await self.post("/api/things", body, authenticated=authenticated, declare_length=False)

                self.assertEqual(response.status_code, 413)
                self.assertLessEqual(body.taken, CAP // MiB + 2)

    async def test_a_body_under_the_cap_reaches_the_route_unchanged(self) -> None:
        text = "a" * (3 * MiB)
        payload = Lazy(0, head=('{"text": "' + text + '"}').encode())

        response = await self.post("/api/things", payload)

        self.assertEqual((response.status_code, response.json()), (200, {"length": 3 * MiB}))

    async def test_an_unauthenticated_body_under_the_cap_is_still_a_401(self) -> None:
        response = await self.post("/api/things", Lazy(0, head=b'{"text": "x"}'), authenticated=False)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["x-auth-required"], "session")

    async def test_a_modules_deliberately_public_route_still_works_and_is_capped_without_a_session(self) -> None:
        small = await self.post("/api/public", Lazy(0, head=b'{"text": "hello"}'), authenticated=False)
        big_body = Lazy(400)
        big = await self.post("/api/public", big_body, authenticated=False, declare_length=False)

        self.assertEqual((small.status_code, small.json()), (200, {"length": 5}))
        self.assertEqual(big.status_code, 413)
        self.assertLessEqual(big_body.taken, CAP // MiB + 2)

    async def test_the_body_is_not_read_for_a_request_that_has_none(self) -> None:
        async with client(self.app, self.session_id) as c:
            self.assertEqual((await c.get("/health")).status_code, 200)
            self.assertEqual((await c.get("/api/auth/status")).status_code, 200)


class MultipartDisguiseTests(Case):
    """A content type is a claim the client makes: it must not buy a bigger cap, or a body read before auth."""

    async def test_a_multipart_content_type_does_not_lift_the_cap_on_a_json_route(self) -> None:
        for authenticated in (False, True):
            with self.subTest(authenticated=authenticated):
                body = Lazy(400)

                response = await self.post(
                    "/api/things", body, authenticated=authenticated, declare_length=False,
                    headers={"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"},
                )

                self.assertEqual(response.status_code, 413)
                self.assertLessEqual(body.taken, CAP // MiB + 2, "FastAPI reads a body whatever its content type says")

    async def test_a_multipart_body_between_the_two_caps_is_still_stopped_on_a_route_that_is_not_an_upload(self) -> None:
        body = Lazy(6)  # more than max_body_bytes (4 MiB), less than max_upload_bytes (8 MiB)

        response = await self.post("/api/public", body, authenticated=False, headers={"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"})

        self.assertEqual(response.status_code, 413)
        self.assertLessEqual(body.taken, CAP // MiB + 2)

    async def test_an_upload_that_lies_about_its_length_is_stopped_at_the_upload_cap(self) -> None:
        # Declares 1 MiB and sends 300: a chunked body with a Content-Length beside it, or a lie the server does not catch.
        body = multipart_of(300)

        response = await self.post("/upload/flow-1", body, declare_length=False, headers={**MULTIPART, "Content-Length": str(MiB)})

        self.assertEqual(response.status_code, 413)
        self.assertLessEqual(body.taken, UPLOAD_CAP // MiB + 2)
        self.assertEqual(self.eneo.calls, [])


class ProxyBodyTests(Case):
    async def proxy(self, body: Lazy, **kwargs):
        return await self.post("/api/eneo/things/", body, headers={"Content-Type": "application/octet-stream", "Origin": ORIGIN, **kwargs.pop("headers", {})}, **kwargs)

    async def test_a_post_over_the_cap_is_413_and_never_reaches_eneo(self) -> None:
        declared, chunked = Lazy(500), Lazy(500)

        first = await self.proxy(declared)
        second = await self.proxy(chunked, declare_length=False)

        self.assertEqual((first.status_code, second.status_code), (413, 413))
        self.assertEqual(declared.taken, 0)
        self.assertLessEqual(chunked.taken, CAP // MiB + 2)
        self.assertEqual(self.eneo.calls, [])

    async def test_a_post_under_the_cap_is_forwarded_byte_for_byte(self) -> None:
        payload = os.urandom(3 * MiB + 17)

        response = await self.proxy(Lazy(0, head=payload))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.eneo.calls[-1]["content"], payload)

    async def test_a_multipart_content_type_does_not_get_a_bigger_cap_through_the_proxy(self) -> None:
        # The ASGI cap leaves multipart alone (forward_upload has its own); the proxy reads no multipart as a stream.
        declared, chunked = multipart_of(500), multipart_of(500)

        first = await self.proxy(declared, headers={"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"})
        second = await self.proxy(chunked, declare_length=False, headers={"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"})

        self.assertEqual((first.status_code, second.status_code), (413, 413))
        self.assertEqual(declared.taken, 0)
        self.assertLessEqual(chunked.taken, CAP // MiB + 2)
        self.assertEqual(self.eneo.calls, [])

    async def test_an_unauthenticated_multipart_to_the_proxy_is_a_401_and_the_body_is_unread(self) -> None:
        body = multipart_of(6)  # within the upload cap: the dependencies answer before a byte is read

        response = await self.proxy(body, authenticated=False, headers={"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(body.taken, 0)


class UploadTests(Case):
    def setUp(self) -> None:
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.temporary = folder.name
        original = tempfile.tempdir
        tempfile.tempdir = folder.name
        self.addCleanup(setattr, tempfile, "tempdir", original)

    async def upload(self, body: Lazy, **kwargs):
        return await self.post("/upload/flow-1", body, headers=kwargs.pop("headers", MULTIPART), **kwargs)

    def open_files(self) -> int:
        return len(os.listdir("/dev/fd"))

    async def test_an_unauthenticated_upload_is_a_401_and_not_a_byte_of_it_is_read(self) -> None:
        body = multipart_of(6)  # within the upload cap, so it is the session that decides

        response = await self.upload(body, authenticated=False)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(body.taken, 0)
        self.assertEqual(os.listdir(self.temporary), [])

    async def test_an_upload_over_the_cap_is_413_for_everyone_before_any_session_is_looked_at(self) -> None:
        for authenticated in (False, True):
            with self.subTest(authenticated=authenticated):
                body = multipart_of(300)

                response = await self.upload(body, authenticated=authenticated)

                self.assertEqual(response.status_code, 413)
                self.assertEqual(body.taken, 0)

    async def test_an_upload_from_another_origin_is_refused_before_it_is_read(self) -> None:
        body = multipart_of(6)

        response = await self.upload(body, headers={**MULTIPART, "Origin": "http://evil.example"})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(body.taken, 0)

    async def test_an_upload_under_the_cap_is_forwarded_whole_and_leaves_nothing_behind(self) -> None:
        files_before = self.open_files()

        response = await self.upload(multipart_of(6))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.eneo.calls[-1]["size"], 6 * MiB)
        self.assertEqual(self.eneo.calls[-1]["filename"], "a.bin")
        self.assertEqual(os.listdir(self.temporary), [])
        self.assertEqual(self.open_files(), files_before)

    async def test_an_upload_over_the_cap_is_413_and_never_read(self) -> None:
        body = multipart_of(300)

        response = await self.upload(body)

        self.assertEqual(response.status_code, 413)
        self.assertEqual(body.taken, 0)
        self.assertEqual(self.eneo.calls, [])

    async def test_an_upload_without_a_length_is_411_and_never_read(self) -> None:
        body = multipart_of(300)

        response = await self.upload(body, declare_length=False)

        self.assertEqual(response.status_code, 411)
        self.assertLessEqual(body.taken, 1)
        self.assertEqual(self.eneo.calls, [])

    async def test_a_text_field_beside_the_file_is_a_400_and_the_rest_is_not_read(self) -> None:
        field = f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="note"\r\n\r\nhello\r\n'.encode()
        body = Lazy(7, field + multipart_head(), MULTIPART_TAIL)

        response = await self.upload(body)

        self.assertEqual(response.status_code, 400)
        self.assertLessEqual(body.taken, 1, "the parse stopped at the field, it did not spool the file first")
        self.assertEqual(self.eneo.calls, [])
        self.assertEqual(os.listdir(self.temporary), [])

    async def test_a_file_under_another_name_or_a_second_file_is_a_400(self) -> None:
        other_name = Lazy(1, multipart_head(name="file"), MULTIPART_TAIL)
        two_files = Lazy(1, multipart_head() + b"x\r\n" + multipart_head(), MULTIPART_TAIL)

        self.assertEqual((await self.upload(other_name)).status_code, 400)
        self.assertEqual((await self.upload(two_files)).status_code, 400)
        self.assertEqual(self.eneo.calls, [])

    async def test_a_body_that_is_not_multipart_is_a_400(self) -> None:
        response = await self.upload(Lazy(0, head=b'{"a": 1}'), headers={"Content-Type": "application/json", "Origin": ORIGIN})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.eneo.calls, [])

    async def test_a_control_character_in_the_file_name_or_content_type_is_a_400_and_is_never_forwarded(self) -> None:
        # What a browser cannot send but an attacker can, and what Starlette hands on: a line break in the quoted
        # file name or in the part's content type would be written into the part headers sent to Eneo.
        cases = {
            "bare LF in the content type": multipart_head(content_type="audio/webm\nX-Injected: 1"),
            "bare LF in the file name": multipart_head(filename="a\nX-Injected: 1.webm"),
            "NUL in the file name": multipart_head(filename="a\x00b.webm"),
            "tab in the file name": multipart_head(filename="a\tb.webm"),
            "DEL in the content type": multipart_head(content_type="audio/webm\x7f"),
        }
        for label, head in cases.items():
            with self.subTest(label):
                response = await self.upload(Lazy(1, head, MULTIPART_TAIL))

                self.assertEqual(response.status_code, 400)
        self.assertEqual(self.eneo.calls, [])

    async def test_a_crlf_cannot_get_a_header_of_its_own_to_eneo(self) -> None:
        # The parser ends the value at the line break: the rest is a part header of its own, which is dropped.
        # Should a parser ever pass the CRLF on in the value, forward_upload refuses it (400).
        for label, head in {
            "in the content type": multipart_head(content_type="audio/webm\r\nX-Injected: 1"),
            "in the file name": multipart_head(filename="a\r\nX-Injected: 1.webm"),
        }.items():
            with self.subTest(label):
                self.eneo.calls.clear()

                response = await self.upload(Lazy(1, head, MULTIPART_TAIL))

                self.assertIn(response.status_code, (200, 400))
                for call in self.eneo.calls:
                    self.assertFalse(any(c < " " for c in call["filename"] + call["content_type"]))
                    self.assertNotIn("X-Injected", call["filename"] + call["content_type"])

    async def test_a_file_name_with_spaces_and_non_ascii_letters_is_forwarded(self) -> None:
        response = await self.upload(Lazy(1, multipart_head(filename="möte ett.webm", content_type="audio/webm"), MULTIPART_TAIL))

        self.assertEqual(response.status_code, 200)
        self.assertEqual((self.eneo.calls[-1]["filename"], self.eneo.calls[-1]["content_type"]), ("möte ett.webm", "audio/webm"))

    async def test_a_file_name_given_only_as_rfc_2231_is_a_400(self) -> None:
        # Starlette does not read filename*=, so the part is a text field to it. Browsers send the name in quotes.
        head = (
            f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"upload_file\"; "
            "filename*=UTF-8''m%C3%B6te.webm\r\nContent-Type: audio/webm\r\n\r\n"
        ).encode()

        response = await self.upload(Lazy(1, head, MULTIPART_TAIL))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.eneo.calls, [])

    async def test_aborted_uploads_leave_no_file_open_and_no_temporary_file(self) -> None:
        # The client goes away after 4 MiB, which is more than a spooled file keeps in memory.
        files_before = self.open_files()
        for _ in range(8):
            await self.abort_upload(4)

        self.assertEqual(os.listdir(self.temporary), [])
        self.assertEqual(self.open_files(), files_before, "no collection of garbage was needed to close them")

    async def abort_upload(self, total_mib: int) -> None:
        """One upload, fed straight to the app, that is dropped after ``total_mib``."""
        pieces = [multipart_head()] + [b"0" * MiB] * total_mib
        headers = {**MULTIPART, "Content-Length": str(len(pieces[0]) + (total_mib + 6) * MiB), "Cookie": f"{SESSION_COOKIE}={self.session_id}"}
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http", "path": "/upload/flow-1",
            "raw_path": b"/upload/flow-1", "query_string": b"", "root_path": "", "client": ("127.0.0.1", 1), "server": ("module.example.test", 80),
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        }
        queue = iter(pieces)

        async def receive():
            piece = next(queue, None)
            if piece is None:
                return {"type": "http.disconnect"}
            return {"type": "http.request", "body": piece, "more_body": True}

        async def send(message) -> None:
            pass

        try:
            await self.app(scope, receive, send)
        except Exception:  # the dropped connection surfaces as an error the server logs; what matters is what is left
            pass


if __name__ == "__main__":
    unittest.main()
