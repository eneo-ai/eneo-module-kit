import tempfile
import time
import unittest
from pathlib import Path

import httpx2
from fastapi.testclient import TestClient

from eneo_module_bff import ModuleSession, ModuleUser, Settings
from eneo_module_bff.auth import SESSION_COOKIE

from main import PROXY_RULES, build_app


def settings() -> Settings:
    return Settings(
        eneo_backend_url="https://eneo.example.test",
        eneo_public_url="https://eneo.example.test",
        module_public_url="https://module.example.test",
        module_key="eneo-module",
        eneo_api_key="service-key",
        session_secret="x" * 48,
        cookie_secure=False,
    )


class TheModuleAsServedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[httpx2.Request] = []

        def eneo(request: httpx2.Request) -> httpx2.Response:
            self.calls.append(request)
            return httpx2.Response(200, json={"items": [{"id": "flow-1", "name": "Ett flöde"}]})

        self.static = tempfile.TemporaryDirectory()
        root = Path(self.static.name)
        (root / "assets").mkdir()
        (root / "index.html").write_text("<!doctype html><title>Modul</title>")
        client = httpx2.AsyncClient(transport=httpx2.MockTransport(eneo))
        app = build_app(settings(), static_dir=root, http_client=client)
        self.client = TestClient(app)
        session = ModuleSession(
            access_token="module-user-token",
            expires_at=int(time.time()) + 600,
            refresh_at=int(time.time()) + 300,
            session_expires_at=int(time.time()) + 3600,
            module_key="eneo-module",
            tenant_id="tenant-id",
            user=ModuleUser(id="user-id", email="erik@example.test", username="Erik Lund"),
        )
        self.cookie = {SESSION_COOKIE: app.state.module_auth.sessions.create(session)}

    def tearDown(self) -> None:
        self.client.close()
        self.static.cleanup()

    def test_health_and_the_page_need_no_session_and_a_deep_link_is_the_page(self) -> None:
        self.assertEqual(self.client.get("/health").json(), {"ok": True})
        deep = self.client.get("/flows")
        self.assertEqual(deep.status_code, 200)
        self.assertIn("<title>Modul</title>", deep.text)

    def test_an_unknown_api_path_and_a_missing_asset_are_404_never_the_page(self) -> None:
        self.assertEqual(self.client.get("/api/nope").status_code, 404)
        self.assertEqual(self.client.get("/missing.js").status_code, 404)

    def test_the_modules_own_route_answers_the_signed_in_user_and_nobody_else(self) -> None:
        refused = self.client.get("/api/example")
        self.assertEqual((refused.status_code, refused.headers.get("X-Auth-Required")), (401, "session"))
        self.client.cookies.set(SESSION_COOKIE, self.cookie[SESSION_COOKIE])
        self.assertEqual(self.client.get("/api/example").json(), {"greeting": "Hej Erik Lund"})

    def test_the_flows_route_goes_to_eneo_with_both_credentials_and_nothing_else_does(self) -> None:
        self.assertEqual(self.client.get("/api/eneo/flows/").status_code, 401, "no session, no call")
        self.client.cookies.set(SESSION_COOKIE, self.cookie[SESSION_COOKIE])
        answer = self.client.get("/api/eneo/flows/")
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer.json()["items"][0]["name"], "Ett flöde")
        sent = self.calls[-1]
        self.assertEqual(str(sent.url), "https://eneo.example.test/api/v1/flows/")
        self.assertEqual(sent.headers["X-API-Key"], "service-key")
        self.assertEqual(sent.headers["Authorization"], "Bearer module-user-token")
        self.assertEqual(self.client.get("/api/eneo/users/").status_code, 403, "denied by default")
        self.assertEqual(len(self.calls), 1, "and the denied one never reached Eneo")

    def test_the_allowlist_is_the_one_route_the_page_lists_flows_with(self) -> None:
        self.assertEqual([(sorted(r.methods), r.pattern.pattern) for r in PROXY_RULES], [(["GET"], "flows/$")])


if __name__ == "__main__":
    unittest.main()
