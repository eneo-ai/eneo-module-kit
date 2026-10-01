"""An answer to the signed-URL request that the module cannot use: a 502, never cached, never a 500, no slot kept."""

import json
import unittest

from fastapi import APIRouter, Depends, Request

from eneo_module_bff.auth import SESSION_COOKIE
from eneo_module_bff.deps import require_session
from eneo_module_bff.transport import stream_signed

from .fake_eneo import Answer, FakeEneo, Module

router = APIRouter()
MINT_PATH = "files/f1/signed-url/"


@router.get("/files/f1", dependencies=[Depends(require_session)])
async def download(request: Request):
    return await stream_signed(request, "f1", mint_path=MINT_PATH, unavailable="no file")


def mint(body: bytes) -> Answer:
    return Answer(body=body)


GOOD = json.dumps({"url": "http://eneo.example/signed/f1?sig=1"}).encode()
BAD_ANSWERS = {
    "a NUL in the path": json.dumps({"url": "http://eneo.example/signed/a\u0000b?sig=1"}).encode(),
    "a NUL in the query": json.dumps({"url": "http://eneo.example/signed/f1?sig=a\u0000b"}).encode(),
    "a URL over the client's length bound": json.dumps({"url": "http://eneo.example/signed/" + "a" * 70_000}).encode(),
    "an expires_at too big for a float": b'{"url": "http://eneo.example/signed/f1?sig=1", "expires_at": 1' + b"0" * 400 + b"}",
    "an expires_at of infinity": b'{"url": "http://eneo.example/signed/f1?sig=1", "expires_at": 1e999}',
    "an expires_at that is a string": b'{"url": "http://eneo.example/signed/f1?sig=1", "expires_at": "soon"}',
}


class MintAnswerTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_answer_the_module_cannot_use_is_a_502_that_is_not_kept_and_frees_its_slot(self) -> None:
        mode = {"body": GOOD}

        def answer(seen):
            if seen.path.endswith("/signed-url/"):
                return mint(mode["body"])
            return Answer(body=b"audio", headers=[("content-type", "audio/wav")])

        eneo = FakeEneo(answer)
        module = Module(self, eneo, routers=(router,), max_concurrent_streams=1)
        browser = module.browser()
        sessions = module.app.state.module_auth.sessions
        session_id = browser.cookies.get(SESSION_COOKIE)
        for label, body in BAD_ANSWERS.items():
            with self.subTest(label):
                sessions.forget_signed_url(session_id, MINT_PATH)
                mode["body"] = body

                response = await browser.get("/files/f1")

                self.assertEqual((response.status_code, response.json()["error"]), (502, "upstream_invalid"))
                self.assertIsNone(sessions.signed_url(session_id, MINT_PATH))
                # The only slot is free again: a good answer streams.
                mode["body"] = GOOD
                good = await browser.get("/files/f1")
                self.assertEqual((good.status_code, good.content), (200, b"audio"))


if __name__ == "__main__":
    unittest.main()
