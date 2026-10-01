"""How the module's one client treats what Eneo sends it."""

import unittest

from eneo_module_bff.proxy import rule

from .fake_eneo import Answer, FakeEneo, Module

RULES = (rule("GET", r"things/$"),)


class CookieTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_cookie_eneo_sets_for_one_user_never_reaches_another_users_call(self) -> None:
        eneo = FakeEneo(lambda seen: Answer(headers=[("content-type", "application/json"), ("set-cookie", "eneo_session=secret-of-a; Path=/")]))
        module = Module(self, eneo, proxy_rules=RULES)
        user_a, user_b = module.browser("a"), module.browser("b")

        await user_a.get("/api/eneo/things/")
        await user_b.get("/api/eneo/things/")
        await user_a.get("/api/eneo/things/")

        self.assertEqual(len(eneo.seen), 3)
        for seen in eneo.seen:
            self.assertNotIn("cookie", seen.headers)
        self.assertEqual(len(module.upstream.cookies.jar), 0)


if __name__ == "__main__":
    unittest.main()
