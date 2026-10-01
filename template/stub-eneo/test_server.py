import json
import threading
import unittest
from http.client import HTTPConnection

import server


class StubEneoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.httpd = server.serve(0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self) -> None:
        server.STATE.__init__()

    def call(self, method: str, path: str, headers: dict | None = None, body: dict | None = None):
        connection = HTTPConnection("127.0.0.1", self.port)
        connection.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers or {})
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response, (json.loads(data) if data and response.getheader("Content-Type") == "application/json" else None)

    KEY = {"X-API-Key": server.API_KEY}

    def ticket(self) -> str:
        response, _ = self.call("GET", f"/module-login?module_key={server.MODULE_KEY}&redirect_uri=http://module.test/api/auth/callback&state=abc")
        self.assertEqual(response.status, 303)
        location = response.getheader("Location")
        self.assertTrue(location.startswith("http://module.test/api/auth/callback?ticket="))
        self.assertTrue(location.endswith("&state=abc"), "the state comes back unchanged")
        return location.split("ticket=")[1].split("&")[0]

    def token(self) -> str:
        response, body = self.call("POST", "/api/v1/module-auth/token/", self.KEY, {"ticket": self.ticket()})
        self.assertEqual(response.status, 200)
        return body["access_token"]

    def test_it_says_when_it_is_up(self) -> None:
        response, body = self.call("GET", "/health")
        self.assertEqual((response.status, body), (200, {"ok": True}))

    def test_the_login_needs_the_modules_key_and_a_callback(self) -> None:
        response, _ = self.call("GET", "/module-login?module_key=other&redirect_uri=http://x/cb&state=s")
        self.assertEqual(response.status, 400)

    def test_a_ticket_buys_one_token_and_only_for_the_service_key(self) -> None:
        ticket = self.ticket()
        refused, _ = self.call("POST", "/api/v1/module-auth/token/", {}, {"ticket": ticket})
        self.assertEqual(refused.status, 401)
        response, body = self.call("POST", "/api/v1/module-auth/token/", self.KEY, {"ticket": ticket})
        self.assertEqual((response.status, body["token_type"], body["module_key"]), (200, "bearer", server.MODULE_KEY))
        self.assertIn("session_expires_at", body)
        again, _ = self.call("POST", "/api/v1/module-auth/token/", self.KEY, {"ticket": ticket})
        self.assertEqual(again.status, 400, "a ticket works once")

    def test_a_resource_call_needs_both_credentials(self) -> None:
        token = self.token()
        bearer = {"Authorization": f"Bearer {token}"}
        for headers in ({}, self.KEY, bearer, {**self.KEY, "Authorization": "Bearer wrong"}):
            response, _ = self.call("GET", "/api/v1/flows/", headers)
            self.assertEqual(response.status, 401, str(headers))
        response, body = self.call("GET", "/api/v1/flows/", {**self.KEY, **bearer})
        self.assertEqual((response.status, len(body["items"])), (200, 2))
        session, who = self.call("GET", f"/api/v1/module-auth/{server.MODULE_KEY}/session/", {**self.KEY, **bearer})
        self.assertEqual((session.status, who["user"]["username"]), (200, "Erik Lund"))
        refreshed, fresh = self.call("POST", f"/api/v1/module-auth/{server.MODULE_KEY}/token/refresh/", {**self.KEY, **bearer})
        self.assertEqual(refreshed.status, 200)
        self.assertNotEqual(fresh["access_token"], token)

    def test_the_controls_end_the_login_and_change_the_list(self) -> None:
        both = {**self.KEY, "Authorization": f"Bearer {self.token()}"}
        self.call("POST", "/__stub/flows?mode=empty")
        self.assertEqual(self.call("GET", "/api/v1/flows/", both)[1]["items"], [])
        self.call("POST", "/__stub/flows?mode=error")
        self.assertEqual(self.call("GET", "/api/v1/flows/", both)[0].status, 500)
        self.call("POST", "/__stub/end-session")
        self.assertEqual(self.call("GET", "/api/v1/flows/", both)[0].status, 401, "Eneo has ended the login")


if __name__ == "__main__":
    unittest.main()
