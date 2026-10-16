"""Which build runs: /health says the commit and the time the image was built from and at, the repository, and the release
the deployment names, each null when it is not known."""

import asyncio
import os
import unittest
from unittest.mock import patch

import httpx2
from fastapi.testclient import TestClient

from eneo_module_bff.app import create_app

from .test_app import make_settings

COMMIT = "c5d54608d5833737677157bde44b95b969e67bbb"
UNKNOWN = {"revision": None, "build_date": None, "release": None, "source": None}


class HealthSaysWhichBuildRuns(unittest.TestCase):
    def health(self, environment: dict[str, str]) -> dict[str, object]:
        """What both health paths answer in an environment of exactly ``environment``."""
        http = httpx2.AsyncClient()
        self.addCleanup(lambda: asyncio.run(http.aclose()))
        with patch.dict(os.environ, environment, clear=True):
            client = TestClient(create_app(make_settings(), http_client=http))
        answers = [client.get(path).json() for path in ("/health", "/api/healthz")]
        self.assertEqual(answers[0], answers[1])
        return answers[0]

    def test_a_build_given_nothing_says_nothing_of_itself(self) -> None:
        self.assertEqual(self.health({}), {"ok": True, **UNKNOWN})

    def test_the_image_says_its_build_and_the_deployment_says_its_release(self) -> None:
        environment = {
            "SOURCE_REVISION": COMMIT,
            "BUILD_DATE": "2026-10-16T08:04:12Z",
            "SOURCE_URL": "https://github.com/eneo-ai/eneo-mod-example",
            "MODULE_VERSION": "v1.2.3",
        }

        self.assertEqual(
            self.health(environment),
            {
                "ok": True,
                "revision": COMMIT,
                "build_date": "2026-10-16T08:04:12Z",
                "release": "v1.2.3",
                "source": "https://github.com/eneo-ai/eneo-mod-example",
            },
        )

    def test_only_a_version_tag_is_a_release(self) -> None:
        # latest and a commit's tag say which image was pulled, not which release it is.
        for version in ("latest", f"sha-{COMMIT}", "1.2.3", "v1.2", "v1.2.3-rc.1", " v1.2.3", ""):
            with self.subTest(version=version):
                self.assertEqual(self.health({"MODULE_VERSION": version}), {"ok": True, **UNKNOWN})

    def test_a_value_of_another_form_is_not_known(self) -> None:
        for name, value in (
            ("SOURCE_REVISION", COMMIT[:7]),
            ("SOURCE_REVISION", COMMIT.upper()),
            ("SOURCE_REVISION", f"{COMMIT}\n"),
            ("BUILD_DATE", "2026-10-16 08:04:12"),
            ("BUILD_DATE", "2026-10-16T08:04:12+02:00"),
            ("BUILD_DATE", "2026-1-6T08:04:12Z"),
            # The repository becomes a link on the page: only an https address is one.
            ("SOURCE_URL", "javascript:alert(1)"),
            ("SOURCE_URL", "http://github.com/eneo-ai/eneo-mod-example"),
            ("SOURCE_URL", "https://github.com/eneo-ai/eneo-mod-example?x=1"),
            ("SOURCE_URL", 'https://github.com/"onmouseover'),
        ):
            with self.subTest(name=name, value=value):
                self.assertEqual(self.health({name: value}), {"ok": True, **UNKNOWN})


if __name__ == "__main__":
    unittest.main()
