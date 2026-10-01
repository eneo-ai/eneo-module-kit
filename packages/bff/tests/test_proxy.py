import time
import unittest

import httpx
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient

from eneo_module_bff.app import create_app
from eneo_module_bff.auth import ModuleSession, ModuleUser, SESSION_COOKIE
from eneo_module_bff.deps import require_same_origin, require_session
from eneo_module_bff.proxy import FORWARDED_REQUEST_HEADERS, RESOURCE_ID, rule
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
    def build(self, rules=PROXY_RULES, routers=(), forward_request_headers=(), **overrides) -> None:
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
        app = create_app(
            settings,
            proxy_rules=rules,
            routers=routers,
            forward_request_headers=forward_request_headers,
            http_client=self.proxy_client,
        )
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

    def test_only_an_allowlist_of_request_headers_reaches_eneo(self) -> None:
        allowed = {
            "Accept": "application/json",
            "Accept-Language": "sv",
            "Content-Type": "application/json",
            "Idempotency-Key": "k-1",
            "If-Match": '"v1"',
            "If-None-Match": '"v2"',
        }
        # Eneo serves every user on one connection pool and every call carries the service key.
        never = {
            "Transfer-Encoding": "chunked",
            "TE": "trailers",
            "Upgrade": "websocket",
            "Proxy-Authorization": "Basic Zm9vOmJhcg==",
            "X-Forwarded-For": "6.6.6.6",
            "X-Forwarded-Host": "evil.example",
            "X-Forwarded-Proto": "http",
            "Forwarded": "for=6.6.6.6",
            "X-Real-IP": "6.6.6.6",
            "X-Space-Id": "space-1",
            "X-Anything-Else": "1",
            "Authorization": "Bearer browser-controlled-token",
            "X-API-Key": "browser-controlled-key",
            "Origin": "https://module.example.test",
            "Referer": "https://module.example.test/x",
        }

        self.client.cookies.set("tracking", "1")  # sent beside the session cookie, as a browser would

        response = self.client.post("/api/eneo/flows/flow-1/runs/", headers={**allowed, **never}, json={})

        self.assertEqual(response.status_code, 200)
        forwarded = {name.lower(): value for name, value in self.proxy_client.calls[0]["headers"].items()}
        for name in allowed:
            self.assertIn(name.lower(), forwarded, name)
        self.assertNotIn("cookie", forwarded)
        for name in never:
            if name.lower() not in ("authorization", "x-api-key"):  # set by the module, from its session
                self.assertNotIn(name.lower(), forwarded, name)
        self.assertEqual(forwarded["authorization"], "Bearer module-user-token")
        self.assertEqual(forwarded["x-api-key"], "test-key")
        self.assertEqual(set(forwarded), set(FORWARDED_REQUEST_HEADERS) | {"authorization", "x-api-key"})

    def test_the_allowlist_is_exactly_these_headers(self) -> None:
        self.assertEqual(
            FORWARDED_REQUEST_HEADERS,
            {"accept", "accept-language", "content-type", "idempotency-key", "if-match", "if-none-match"},
        )

    def test_a_module_can_add_headers_to_the_allowlist(self) -> None:
        self.build(forward_request_headers=["X-Request-Id", "x-tenant-hint"])

        self.client.get(
            "/api/eneo/flows/",
            headers={"X-Request-Id": "r-1", "X-Tenant-Hint": "t", "X-Forwarded-For": "6.6.6.6"},
        )

        forwarded = {name.lower(): value for name, value in self.proxy_client.calls[0]["headers"].items()}
        self.assertEqual((forwarded["x-request-id"], forwarded["x-tenant-hint"]), ("r-1", "t"))
        self.assertNotIn("x-forwarded-for", forwarded)

    def test_a_module_cannot_add_a_credential_or_a_framing_header(self) -> None:
        for name in ("Cookie", "authorization", "ORIGIN", "Referer", "X-API-Key", "Host", "Content-Length", "Transfer-Encoding"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.build(forward_request_headers=[name])

    def test_the_configured_api_key_header_stays_the_modules_even_if_a_module_lists_it(self) -> None:
        self.build(forward_request_headers=["X-Eneo-Module-Key"], eneo_api_key_header_name="X-Eneo-Module-Key")

        self.client.get("/api/eneo/flows/", headers={"X-Eneo-Module-Key": "browser-controlled-key"})

        headers = self.proxy_client.calls[0]["headers"]
        self.assertEqual([value for name, value in headers.items() if name.lower() == "x-eneo-module-key"], ["test-key"])

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

    def test_a_modules_own_route_under_api_eneo_wins_and_the_proxy_still_denies_the_rest(self) -> None:
        router = APIRouter()

        @router.post(
            "/api/eneo/things/{thing_id}/files",
            dependencies=[Depends(require_session), Depends(require_same_origin)],
        )
        async def upload(thing_id: str) -> dict[str, str]:
            return {"own": thing_id}

        self.build(rules=(), routers=[router])
        origin = {"Origin": "https://module.example.test"}

        self.assertEqual(self.client.post("/api/eneo/things/1/files", headers=origin).json(), {"own": "1"})
        # The route is the module's, so it declares its own checks, and they hold.
        self.assertEqual(self.client.post("/api/eneo/things/1/files").status_code, 403)
        # Everything else under /api/eneo/ is still denied by default, and Eneo is never called.
        for method, path in (
            ("GET", "/api/eneo/things/"),
            ("POST", "/api/eneo/things/1/other"),
            ("GET", "/api/eneo/things/1/files"),
        ):
            self.assertEqual(self.client.request(method, path, headers=origin).status_code, 403, f"{method} {path}")
        self.assertEqual(self.proxy_client.calls, [])

        self.client.cookies.clear()
        self.assertEqual(self.client.post("/api/eneo/things/1/files", headers=origin).status_code, 401)

    def test_without_a_session_the_proxy_is_401_before_its_rules_are_consulted(self) -> None:
        self.client.cookies.clear()

        for path in ("/api/eneo/flows/", "/api/eneo/users/"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 401, path)
            self.assertEqual(response.headers["x-auth-required"], "session")
        self.assertEqual(self.proxy_client.calls, [])


if __name__ == "__main__":
    unittest.main()
