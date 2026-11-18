"""The login's end against the template's stub Eneo, as a module meets it: a real sign-in through the stub, a token whose
refresh is not due, and the calls to Eneo's session route and refresh counted, so that what ends a session is seen to
be the confirmation and never a refresh.

The stub is ``template/stub-eneo/server.py`` of this checkout, run in a thread. This test lives with the package, not
the template, so that it never ships in a module: the routes below exist only to reach the kit's own parts.
"""

import importlib.util
import threading
import unittest
from pathlib import Path
from urllib.parse import urlsplit

import httpx2
from fastapi import APIRouter, Depends, Request
from fastapi.testclient import TestClient

from eneo_module_bff import create_app, forward_upload, raise_if_session_ended, require_session, rule, stream_signed, upstream_auth_headers
from eneo_module_bff.settings import Settings

_STUB = Path(__file__).resolve().parents[3] / "template" / "stub-eneo" / "server.py"
_spec = importlib.util.spec_from_file_location("stub_eneo_server", _STUB)
stub = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stub)

ORIGIN = "http://127.0.0.1:3999"  # the module, as the stub sends the browser back to it; never listened on
ENDED = {"detail": "Not authenticated"}
REFUSED = {"message": "Unauthenticated", "eneo_error_code": 9005, "code": "authentication_error"}

router = APIRouter()


@router.post("/api/upload", dependencies=[Depends(require_session)])
async def upload(request: Request):
    return await forward_upload(request, "files/")


@router.get("/api/file", dependencies=[Depends(require_session)])
async def file(request: Request):
    return await stream_signed(request, "file-1", mint_path="files/file-1/signed-url/", unavailable="The file is not available")


@router.get("/api/own", dependencies=[Depends(require_session)])
async def own(request: Request):
    eneo = request.app.state.settings.eneo_backend_url
    answer = await request.app.state.http.get(f"{eneo}/api/v1/flows/", headers=upstream_auth_headers(request))
    await raise_if_session_ended(request, answer)
    return {"eneo": answer.status_code}


# What each route answers when Eneo's refusal goes on: its own contract for an answer that is not the login's end.
SITES = {
    "the proxy": (lambda browser: browser.get("/api/eneo/flows/"), lambda answer: answer.json() == REFUSED),
    "a forwarded upload": (
        lambda browser: browser.post("/api/upload", files={"upload_file": ("note.txt", b"text", "text/plain")}),
        lambda answer: answer.json() == REFUSED,
    ),
    "the minting of a signed URL": (lambda browser: browser.get("/api/file"), lambda answer: answer.json() == {"detail": REFUSED}),
    "a module's own call": (lambda browser: browser.get("/api/own"), lambda answer: answer.json() == {"eneo": 401}),
}


class AgainstTheStubTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.httpd = stub.serve(0)
        cls.eneo = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self) -> None:
        stub.STATE.__init__()
        settings = Settings(
            eneo_backend_url=self.eneo,
            eneo_public_url=self.eneo,
            module_public_url=ORIGIN,
            module_key=stub.MODULE_KEY,
            eneo_api_key=stub.API_KEY,
            session_secret="x" * 48,
            cookie_secure=False,
        )
        app = create_app(settings, routers=[router], proxy_rules=[rule("GET", r"flows/$")])
        self.browser = self.enterContext(TestClient(app, base_url=ORIGIN, follow_redirects=False))

    def stub_control(self, method: str, path: str) -> dict:
        answer = httpx2.request(method, f"{self.eneo}{path}")
        self.assertEqual(answer.status_code, 200, answer.text)
        return answer.json()

    def sign_in(self) -> None:
        """The login as a browser does it: the module sends it to the stub, the stub back to the callback."""
        to_eneo = self.browser.get("/api/auth/login?next=/flows").headers["location"]
        callback = httpx2.get(to_eneo).headers["location"]
        self.assertTrue(callback.startswith(f"{ORIGIN}/api/auth/callback?"), callback)
        landed = self.browser.get(urlsplit(callback)._replace(scheme="", netloc="").geturl())
        self.assertEqual((landed.status_code, landed.headers["location"]), (303, "/flows"))
        status = self.browser.get("/api/auth/status").json()
        self.assertTrue(status["authenticated"])
        self.assertGreater(status["refresh_in"], 60, "a token whose refresh is not due: nothing but a refusal can end it")

    def signed_in(self) -> bool:
        return self.browser.get("/api/auth/status").json()["authenticated"]

    def test_a_login_eneo_ended_ends_the_session_at_every_call_and_no_refresh_did_it(self) -> None:
        for site, (send, _) in SITES.items():
            with self.subTest(site):
                self.sign_in()
                before = self.stub_control("GET", "/__stub/calls")
                self.stub_control("POST", "/__stub/end-session")

                answer = send(self.browser)

                self.assertEqual((answer.status_code, answer.json()), (401, ENDED), answer.text)
                self.assertEqual(answer.headers.get("x-auth-required"), "session")
                self.assertFalse(self.signed_in())
                calls = self.stub_control("GET", "/__stub/calls")
                self.assertEqual(calls["session_route"] - before["session_route"], 1, "one check, which confirmed the end")
                self.assertEqual(calls["refresh"], 0)

    def test_a_refusal_the_session_route_does_not_confirm_goes_on_and_the_session_stays(self) -> None:
        for site, (send, as_before) in SITES.items():
            with self.subTest(site):
                self.sign_in()
                before = self.stub_control("GET", "/__stub/calls")
                self.stub_control("POST", "/__stub/resources?answer=refused")

                answer = send(self.browser)

                self.assertNotIn("x-auth-required", answer.headers)
                self.assertTrue(as_before(answer), answer.text)
                self.assertTrue(self.signed_in())
                calls = self.stub_control("GET", "/__stub/calls")
                self.assertEqual(calls["session_route"] - before["session_route"], 1, "one check, which confirmed nothing")
                self.assertEqual(calls["refresh"], 0)
                self.stub_control("POST", "/__stub/resources?answer=normal")


if __name__ == "__main__":
    unittest.main()
