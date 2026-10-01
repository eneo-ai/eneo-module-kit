"""The path Eneo receives is the path the module authorised, however the browser wrote it."""

import json
import unittest

from fastapi import APIRouter, Depends, Request

from eneo_module_bff.deps import require_same_origin, require_session
from eneo_module_bff.proxy import RESOURCE_ID, rule
from eneo_module_bff.transport import forward_upload, stream_signed

from .fake_eneo import Answer, FakeEneo, Module

RULES = (rule("GET", rf"things/{RESOURCE_ID}/$"),)

router = APIRouter()


@router.post("/upload/{flow_id}", dependencies=[Depends(require_session), Depends(require_same_origin)])
async def upload(flow_id: str, request: Request):
    return await forward_upload(request, f"flows/{flow_id}/files/")


@router.get("/files/{file_id}", dependencies=[Depends(require_session)])
async def download(file_id: str, request: Request):
    return await stream_signed(request, file_id, mint_path=f"files/{file_id}/signed-url/", unavailable="no file")


def eneo_with_files(seen) -> Answer:
    if seen.path.endswith("/signed-url/"):
        return Answer(body=json.dumps({"url": "http://eneo.example/signed/f?sig=1"}).encode())
    return Answer(body=b"audio", headers=[("content-type", "audio/wav")])


class ProxyPathTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.eneo = FakeEneo()
        self.browser = Module(self, self.eneo, proxy_rules=RULES).browser()

    async def test_a_double_encoded_slash_stays_one_path_segment_upstream(self) -> None:
        # %252F is the three characters "%2F" in one resource id. Sent as they are, Eneo would decode them once more
        # and serve things/a/export/, a route the rule never allowed.
        response = await self.browser.get("/api/eneo/things/a%252Fexport/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.eneo.seen[0].path, "/api/v1/things/a%2Fexport/")

    async def test_an_ordinary_id_arrives_as_it_was_sent(self) -> None:
        for sent, arrives in (("abc-123", "abc-123"), ("a%20b", "a b"), ("%C3%A5ngest", "ångest"), ("a%3Bb", "a;b")):
            with self.subTest(sent=sent):
                self.eneo.seen.clear()

                response = await self.browser.get(f"/api/eneo/things/{sent}/")

                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.eneo.seen[0].path, f"/api/v1/things/{arrives}/")


class UploadAndMintPathTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.eneo = FakeEneo(eneo_with_files)
        self.browser = Module(self, self.eneo, routers=(router,)).browser()

    async def test_an_upload_path_with_a_double_encoded_slash_stays_one_segment(self) -> None:
        response = await self.browser.post("/upload/a%252Fb", files={"upload_file": ("a.bin", b"x", "application/octet-stream")})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.eneo.seen[0].path, "/api/v1/flows/a%2Fb/files/")

    async def test_a_mint_path_with_a_double_encoded_slash_stays_one_segment(self) -> None:
        response = await self.browser.get("/files/a%252Fb")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.eneo.seen[0].path, "/api/v1/files/a%2Fb/signed-url/")


if __name__ == "__main__":
    unittest.main()
