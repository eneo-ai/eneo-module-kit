import time
import unittest

import httpx
from fastapi.testclient import TestClient

from eneo_module_bff.app import create_app
from eneo_module_bff.auth import ModuleSession, ModuleUser, SESSION_COOKIE
from eneo_module_bff.proxy import RESOURCE_ID, rule
from eneo_module_bff.settings import Settings

# The kit ships no rules; these are what the test module allows.
PROXY_RULES = [
    rule("GET", r"flows/$"),
    rule({"GET", "POST"}, rf"flows/{RESOURCE_ID}/runs/$"),
]


class FakeResponse:
    content = b'{"items":[]}'
    status_code = 200
    headers = {"content-type": "application/json"}


class FakeProxyClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def request(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse()


class EneoProxyAuthTests(unittest.TestCase):
    def build(self, rules=PROXY_RULES, **overrides) -> None:
        settings = Settings(
            eneo_backend_url="https://eneo.example.test",
            eneo_public_url="https://eneo.example.test",
            module_public_url="https://module.example.test",
            module_key="speech-to-text",
            eneo_api_key="test-key",
            session_secret="x" * 48,
            cookie_secure=False,
            **overrides,
        )
        self.proxy_client = FakeProxyClient()
        app = create_app(settings, proxy_rules=rules, http_client=self.proxy_client)
        self.client = TestClient(app)
        session = ModuleSession(
            access_token="module-user-token",
            expires_at=int(time.time()) + 60,
            refresh_at=int(time.time()) + 30,
            session_expires_at=int(time.time()) + 3600,
            module_key="speech-to-text",
            tenant_id="tenant-id",
            user=ModuleUser(id="user-id", email="user@example.test"),
        )
        session_id = app.state.module_auth.sessions.create(session)
        self.client.cookies.set(
            SESSION_COOKIE,
            session_id,
        )

    def setUp(self) -> None:
        self.build()

    def test_proxy_replaces_browser_credentials_with_module_credentials(self) -> None:
        response = self.client.get(
            "/api/eneo/flows/?published=true",
            headers={
                "Authorization": "Bearer browser-controlled-token",
                "X-API-Key": "browser-controlled-key",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.proxy_client.calls), 1)
        call = self.proxy_client.calls[0]
        self.assertEqual(
            call["url"],
            "https://eneo.example.test/api/v1/flows/",
        )
        self.assertEqual(call["params"]["published"], "true")
        self.assertEqual(call["headers"]["X-API-Key"], "test-key")
        self.assertEqual(
            call["headers"]["Authorization"],
            "Bearer module-user-token",
        )

    def test_mutation_rejects_cross_origin_request_before_proxying(self) -> None:
        response = self.client.post(
            "/api/eneo/flows/flow-id/runs/",
            headers={"Origin": "https://attacker.example.test"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.proxy_client.calls, [])

    def test_proxy_never_forwards_the_browsers_origin_to_eneo(self) -> None:
        # The module checks the browser's Origin itself. Eneo refuses any origin it does not
        # list, so passing the module's own hostname on would fail every write in production.
        response = self.client.post(
            "/api/eneo/flows/flow-1/runs/",
            headers={
                "Origin": "https://module.example.test",
                "Referer": "https://module.example.test/flows/flow-1",
            },
            json={"expected_run_revision": 2, "expected_correction_revision": None, "segments_hash": "a" * 64},
        )

        self.assertEqual(response.status_code, 200)
        forwarded = {name.lower() for name in self.proxy_client.calls[0]["headers"]}
        self.assertNotIn("origin", forwarded)
        self.assertNotIn("referer", forwarded)

    def test_proxy_forwards_flow_discovery_across_the_users_spaces(self) -> None:
        response = self.client.get("/api/eneo/flows/?published_only=true&limit=200&offset=0")

        self.assertEqual(response.status_code, 200)
        call = self.proxy_client.calls[0]
        self.assertEqual(call["url"], "https://eneo.example.test/api/v1/flows/")
        self.assertEqual(dict(call["params"]), {"published_only": "true", "limit": "200", "offset": "0"})

    def test_proxy_no_longer_exposes_spaces(self) -> None:
        # Discovery lists flows across spaces; the spaces routes refuse module credentials anyway.
        for path in ("/api/eneo/spaces/", "/api/eneo/spaces/space-1/"):
            self.assertEqual(self.client.get(path).status_code, 403, path)
        self.assertEqual(self.proxy_client.calls, [])

    def test_proxy_rejects_resource_outside_module_allowlist(self) -> None:
        response = self.client.post(
            "/api/eneo/users/",
            headers={"Origin": "https://module.example.test"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.proxy_client.calls, [])

    def test_proxy_rejects_encoded_dot_segment_traversal(self) -> None:
        # `%2E%2E` survives ASGI path normalization and decodes to `..`, which
        # would resolve upstream to /api/v1/flows/../runs/ -> /api/v1/runs/.
        response = self.client.get("/api/eneo/flows/%2E%2E/runs/")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.proxy_client.calls, [])

    def test_proxy_rejects_single_dot_segment(self) -> None:
        response = self.client.get("/api/eneo/flows/%2E/runs/")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.proxy_client.calls, [])

    def test_proxy_rejects_an_encoded_query_or_fragment_in_a_segment(self) -> None:
        # `flows/x%3F/runs/` matches the allowlist but would reach
        # /api/v1/flows/x upstream, with the rest moved into the query.
        for path in ("/api/eneo/flows/x%3F/runs/", "/api/eneo/flows/x%23/runs/"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 403, path)
        self.assertEqual(self.proxy_client.calls, [])

    def test_with_no_rules_every_path_is_refused_and_eneo_is_never_called(self) -> None:
        self.build(rules=())

        for method, path in (
            ("GET", "/api/eneo/flows/"),
            ("GET", "/api/eneo/flows/flow-1/runs/"),
            ("POST", "/api/eneo/flows/flow-1/runs/"),
            ("PATCH", "/api/eneo/flows/flow-1/"),
        ):
            response = self.client.request(method, path, headers={"Origin": "https://module.example.test"})
            self.assertEqual(response.status_code, 403, f"{method} {path}")
            self.assertEqual(response.json(), {"detail": "Eneo resource is not exposed"})
        self.assertEqual(self.proxy_client.calls, [])

    def test_a_rule_allows_exactly_its_methods(self) -> None:
        origin = {"Origin": "https://module.example.test"}

        self.assertEqual(self.client.get("/api/eneo/flows/flow-1/runs/").status_code, 200)
        self.assertEqual(self.client.post("/api/eneo/flows/flow-1/runs/", headers=origin).status_code, 200)
        allowed = len(self.proxy_client.calls)

        self.assertEqual(self.client.post("/api/eneo/flows/", headers=origin).status_code, 403)
        self.assertEqual(self.client.patch("/api/eneo/flows/flow-1/runs/", headers=origin).status_code, 403)
        self.assertEqual(len(self.proxy_client.calls), allowed)

    def test_a_path_must_match_a_rule_as_written(self) -> None:
        # No trailing-slash tolerance, no prefix match.
        for path in (
            "/api/eneo/flows",
            "/api/eneo/flows/flow-1/runs",
            "/api/eneo/flows/flow-1/runs/extra/",
            "/api/eneo/flows/flow-1/runs//",
            "/api/eneo/users",
        ):
            self.assertEqual(self.client.get(path).status_code, 403, path)
        self.assertEqual(self.proxy_client.calls, [])

    def test_the_callers_other_headers_are_forwarded_but_never_its_cookie_or_routing_headers(self) -> None:
        response = self.client.post(
            "/api/eneo/flows/flow-1/runs/",
            headers={
                "Origin": "https://module.example.test",
                "Idempotency-Key": "flow-run:1",
                "X-Space-Id": "space-1",
                "X-Upload-Timeout-Seconds": "120",
            },
        )

        self.assertEqual(response.status_code, 200)
        forwarded = {name.lower(): value for name, value in self.proxy_client.calls[0]["headers"].items()}
        self.assertEqual(forwarded["idempotency-key"], "flow-run:1")
        for name in ("cookie", "x-space-id", "x-upload-timeout-seconds", "host", "content-length"):
            self.assertNotIn(name, forwarded)

    def test_a_custom_api_key_header_is_set_by_the_module_never_by_the_browser(self) -> None:
        self.build(eneo_api_key_header_name="X-Eneo-Module-Key")

        self.client.get("/api/eneo/flows/", headers={"X-Eneo-Module-Key": "browser-controlled-key"})

        headers = self.proxy_client.calls[0]["headers"]
        self.assertEqual([value for name, value in headers.items() if name.lower() == "x-eneo-module-key"], ["test-key"])

    def test_the_proxy_answers_502_when_eneo_cannot_be_reached(self) -> None:
        async def unreachable(**_):
            raise httpx.ConnectError("unreachable")

        self.proxy_client.request = unreachable

        with self.assertLogs("eneo_proxy", level="ERROR"):
            response = self.client.get("/api/eneo/flows/")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json(),
            {"error": "upstream_unreachable", "detail": "Eneo could not be reached."},
        )

    def test_without_a_session_the_proxy_is_401_before_its_rules_are_consulted(self) -> None:
        self.client.cookies.clear()

        for path in ("/api/eneo/flows/", "/api/eneo/users/"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 401, path)
            self.assertEqual(response.headers["x-auth-required"], "session")
        self.assertEqual(self.proxy_client.calls, [])


if __name__ == "__main__":
    unittest.main()
