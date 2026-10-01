import unittest

import httpx2
from fastapi.testclient import TestClient

from eneo_module_bff.app import create_app
from eneo_module_bff.settings import LogoFile, Organization, Settings

DEFAULT_ORGANIZATION = Organization(name="Sundsvalls kommun", logo="default")
SVG =b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 4"></svg>'
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000b49444154789c6360000200000500017a5eab3f0000000049454e44ae426082")  # a real 1x1 PNG


class BrandingRouteTests(unittest.TestCase):
    """The login page shows the organisation before there is a session, so neither route asks for one."""

    def use(self, organization, logo=None, dark=None) -> None:
        settings = Settings(
            eneo_backend_url="https://eneo.example.test",
            eneo_public_url="https://eneo.example.test",
            module_public_url="https://module.example.test",
            module_key="speech-to-text",
            eneo_api_key="test-key",
            session_secret="x" * 48,
            cookie_secure=False,
            organization=organization,
            organization_logo=logo,
            organization_logo_dark=dark,
        )
        self.client = TestClient(create_app(settings, http_client=httpx2.AsyncClient()))

    def test_the_branding_says_who_is_shown_without_a_session(self) -> None:
        self.use(DEFAULT_ORGANIZATION)
        self.assertEqual(
            self.client.get("/api/branding").json(),
            {"organization": {"name": "Sundsvalls kommun", "logo": "default", "dark_logo": False}},
        )
        self.use(None)
        self.assertEqual(self.client.get("/api/branding").json(), {"organization": None})

    def test_a_deployments_logo_is_served_same_origin_as_what_it_is(self) -> None:
        self.use(
            Organization(name="Umeå kommun", logo="custom", dark_logo=True),
            LogoFile(media_type="image/svg+xml", content=SVG),
            LogoFile(media_type="image/png", content=PNG),
        )

        light = self.client.get("/api/branding/logo/light")
        dark = self.client.get("/api/branding/logo/dark")

        self.assertEqual((light.status_code, light.content), (200, SVG))
        self.assertEqual(light.headers["content-type"], "image/svg+xml")
        self.assertEqual((dark.status_code, dark.content), (200, PNG))
        self.assertEqual(dark.headers["content-type"], "image/png")
        for response in (light, dark):
            self.assertEqual(response.headers["x-content-type-options"], "nosniff")
            self.assertEqual(response.headers["cache-control"], "no-cache")
            # An SVG opened on its own runs nothing in the module's origin.
            self.assertIn("sandbox", response.headers["content-security-policy"])

    def test_no_logo_file_is_not_found(self) -> None:
        self.use(Organization(name="Umeå kommun", logo=None))
        self.assertEqual(self.client.get("/api/branding/logo/light").status_code, 404)
        self.use(
            Organization(name="Umeå kommun", logo="custom"),
            LogoFile(media_type="image/svg+xml", content=SVG),
        )
        self.assertEqual(self.client.get("/api/branding/logo/dark").status_code, 404)
        self.assertEqual(self.client.get("/api/branding/logo/other").status_code, 422)


if __name__ == "__main__":
    unittest.main()
