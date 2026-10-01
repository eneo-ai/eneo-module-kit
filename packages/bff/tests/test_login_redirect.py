"""Where a refused renewal or a finished login sends the browser: a path of the module, whatever ``next`` says."""

import re
import unittest
from urllib.parse import urlsplit

from eneo_module_bff.auth import module_path

from .fake_eneo import FakeEneo, Module

VECTORS = {
    "a tab": "/\t/review.example",
    "a carriage return": "/\r/review.example",
    "a line feed": "/\n/review.example",
    "a backslash": "/\\review.example",
    "a slash then a backslash": "/\\/review.example",
    "two slashes": "//review.example",
    "a tab after the slash": "/\treview.example",
    "a NUL": "/\x00/review.example",
    "a line separator": "/ /review.example",
    "a C1 control": "/\x85/review.example",
}


def as_a_browser_reads(location: str) -> str:
    """The URL a browser follows: it removes tab, CR and LF from a URL before it parses it."""
    return re.sub(r"[\t\r\n]", "", location)


class LoginRedirectTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.module = Module(self, FakeEneo())

    async def test_a_refused_renewal_stays_on_the_module_whatever_next_holds(self) -> None:
        signed_out = self.module.browser(signed_in=False)
        for label, value in VECTORS.items():
            with self.subTest(label):
                response = await signed_out.get("/api/auth/login", params={"next": value, "renew": "true"})

                location = as_a_browser_reads(response.headers["location"])
                self.assertEqual(response.status_code, 303)
                self.assertFalse(location.startswith(("//", "/\\")), location)
                self.assertEqual(urlsplit(location).netloc, "", location)
                self.assertTrue(location.startswith("/"), location)

    async def test_a_good_next_is_kept(self) -> None:
        signed_out = self.module.browser(signed_in=False)

        response = await signed_out.get("/api/auth/login", params={"next": "/review/123?tab=a#top", "renew": "true"})

        self.assertEqual(response.headers["location"], "/review/123?tab=a&fel=utgangen#top")

    def test_module_path_is_a_short_path_of_the_module_and_nothing_else(self) -> None:
        for label, value in VECTORS.items():
            with self.subTest(label):
                self.assertEqual(module_path(value, "/home"), "/home")
        for value in ("/", "/a/b", "/a?b=c", "/a%09b", "/%09/review.example", "/ångest"):
            with self.subTest(value=value):
                self.assertEqual(module_path(value, "/home"), value)


if __name__ == "__main__":
    unittest.main()
