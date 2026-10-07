import unittest

import httpx2
from fastapi.testclient import TestClient

from eneo_module_bff.accent import NO_ACCENT_CSS, Accent, etag, theme_css
from eneo_module_bff.app import create_app
from eneo_module_bff.settings import LogoFile, Organization, Settings

DEFAULT_ORGANIZATION = Organization(name="Sundsvalls kommun", logo="default")
GREEN = Accent(light="#1E7B34", dark="#2AAE4A", on_light="#FFFFFF", on_dark="#0B1118")
SVG =b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 4"></svg>'
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000b49444154789c6360000200000500017a5eab3f0000000049454e44ae426082")  # a real 1x1 PNG


class BrandingRouteTests(unittest.TestCase):
    """The login page shows the organisation before there is a session."""

    def use(self, organization, logo=None, dark=None, *, accent: Accent | None = None) -> None:
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
            accent=accent,
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

    def test_the_default_logo_is_the_modules_own_and_the_kit_serves_no_file_for_it(self) -> None:
        self.use(DEFAULT_ORGANIZATION)

        self.assertEqual(self.client.get("/api/branding").json()["organization"]["logo"], "default")
        for variant in ("light", "dark"):
            self.assertEqual(self.client.get(f"/api/branding/logo/{variant}").status_code, 404)

    def test_no_logo_file_is_not_found(self) -> None:
        self.use(Organization(name="Umeå kommun", logo=None))
        self.assertEqual(self.client.get("/api/branding/logo/light").status_code, 404)
        self.use(
            Organization(name="Umeå kommun", logo="custom"),
            LogoFile(media_type="image/svg+xml", content=SVG),
        )
        self.assertEqual(self.client.get("/api/branding/logo/dark").status_code, 404)
        self.assertEqual(self.client.get("/api/branding/logo/other").status_code, 422)


    def test_without_an_accent_it_is_a_valid_empty_cacheable_stylesheet(self) -> None:
        self.use(None)
        response = self.client.get("/api/branding/theme.css")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, NO_ACCENT_CSS)
        self.assertTrue(response.headers["content-type"].startswith("text/css"))
        self.assertEqual(response.headers["cache-control"], "public, max-age=300")

    def test_the_accent_is_served_as_the_stylesheet_of_the_validated_colours(self) -> None:
        self.use(None, accent=GREEN)
        response = self.client.get("/api/branding/theme.css")
        self.assertEqual(response.text, theme_css(GREEN))
        self.assertIn("--color-accent: light-dark(#1E7B34, #2AAE4A);", response.text)

    def test_it_is_served_safely_and_without_user_data(self) -> None:
        self.use(None, accent=GREEN)
        response = self.client.get("/api/branding/theme.css", headers={"Cookie": "module_session=secret"})
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["cache-control"], "public, max-age=300")
        self.assertNotIn("set-cookie", response.headers)
        self.assertNotIn("vary", response.headers)
        self.assertNotIn("secret", response.text)

    def test_the_etag_lets_a_browser_revalidate_for_nothing(self) -> None:
        self.use(None, accent=GREEN)
        first = self.client.get("/api/branding/theme.css")
        self.assertEqual(first.headers["etag"], etag(theme_css(GREEN)))
        for header in (first.headers["etag"], "W/" + first.headers["etag"], '"other", ' + first.headers["etag"], "*"):
            again = self.client.get("/api/branding/theme.css", headers={"If-None-Match": header})
            self.assertEqual((again.status_code, again.content), (304, b""), header)
            self.assertEqual(again.headers["etag"], first.headers["etag"])
            self.assertEqual(again.headers["cache-control"], "public, max-age=300")
        self.assertEqual(self.client.get("/api/branding/theme.css", headers={"If-None-Match": '"old"'}).status_code, 200)

    def test_each_app_keeps_its_own_accent_and_content_etag(self) -> None:
        self.use(None, accent=GREEN)
        green_client = self.client
        self.use(None)
        green = green_client.get("/api/branding/theme.css")
        default = self.client.get("/api/branding/theme.css")
        self.assertEqual(green.text, theme_css(GREEN))
        self.assertEqual(default.text, NO_ACCENT_CSS)
        self.assertNotEqual(green.headers["etag"], default.headers["etag"])


if __name__ == "__main__":
    unittest.main()
