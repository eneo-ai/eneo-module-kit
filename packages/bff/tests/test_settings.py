import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from pydantic import ValidationError

from eneo_module_bff.settings import Organization, Settings, canonical_origin, load_settings

SUNDSVALL = Organization(name="Sundsvalls kommun", logo="default")
PNG =bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000b49444154789c6360000200000500017a5eab3f0000000049454e44ae426082")  # a real 1x1 PNG
SVG = b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 4"></svg>'


def valid_environment() -> dict[str, str]:
    return {
        "ENEO_BACKEND_URL": "http://backend:8000",
        "ENEO_PUBLIC_URL": "https://eneo.example.test",
        "MODULE_PUBLIC_URL": "https://module.example.test",
        "MODULE_KEY": "speech-to-text",
        "ENEO_API_KEY": "test-key",
        "SESSION_SECRET": "x" * 48,
        "COOKIE_SECURE": "true",
    }


class SettingsTests(unittest.TestCase):
    def test_the_accent_is_independent_of_the_organization_and_derives_dark_mode(self) -> None:
        with patch.dict(os.environ, valid_environment(), clear=True):
            self.assertIsNone(load_settings().accent)
        with patch.dict(os.environ, valid_environment() | {
            "SHOW_ORGANIZATION": "false", "ORGANIZATION_ACCENT": " #1e7b34\n",
        }, clear=True):
            settings = load_settings()
        self.assertIsNone(settings.organization)
        self.assertEqual(
            (settings.accent.light, settings.accent.dark, settings.accent.on_light, settings.accent.on_dark),
            ("#1E7B34", "#2AAE4A", "#FFFFFF", "#0B1118"),
        )

    def test_an_unusable_accent_refuses_start_up(self) -> None:
        cases = (
            ({"ORGANIZATION_ACCENT": "#FFD700"}, "ORGANIZATION_ACCENT=#FFD700: accentfärgen mot sidans ytor når 1,23:1 i ljust läge"),
            ({"ORGANIZATION_ACCENT": "blue"}, "ORGANIZATION_ACCENT måste vara en färg på formen #RRGGBB"),
            ({"ORGANIZATION_ACCENT_DARK": "#52B1FF"}, "ORGANIZATION_ACCENT_DARK kräver ORGANIZATION_ACCENT"),
            ({"ORGANIZATION_ACCENT": "#004595", "ORGANIZATION_ACCENT_DARK": "#004595"}, "ORGANIZATION_ACCENT_DARK=#004595: accentfärgen mot sidans ytor når"),
        )
        for values, message in cases:
            with self.subTest(values=values), patch.dict(os.environ, valid_environment() | values, clear=True):
                with self.assertRaises(RuntimeError) as raised:
                    load_settings()
                self.assertTrue(str(raised.exception).startswith(message), str(raised.exception))
        with patch.dict(os.environ, valid_environment() | {
            "ORGANIZATION_ACCENT": "#004595", "ORGANIZATION_ACCENT_DARK": "#52b1ff",
        }, clear=True):
            self.assertEqual(load_settings().accent.dark, "#52B1FF")

    def test_heavy_admission_and_receive_deadlines_have_validated_operator_controls(self) -> None:
        with patch.dict(os.environ, valid_environment(), clear=True):
            base = load_settings()
        self.assertEqual((base.max_concurrent_uploads, base.max_concurrent_heavy_io), (1, 64))
        self.assertEqual((base.upload_receive_timeout_seconds, base.upload_receive_idle_timeout_seconds), (1800, 30))
        with patch.dict(os.environ, valid_environment() | {
            "MAX_CONCURRENT_UPLOADS": "2", "MAX_CONCURRENT_HEAVY_IO": "8",
            "UPLOAD_RECEIVE_TIMEOUT_SECONDS": "900", "UPLOAD_RECEIVE_IDLE_TIMEOUT_SECONDS": "45",
        }, clear=True):
            selected = load_settings()
        self.assertEqual((selected.max_concurrent_uploads, selected.max_concurrent_heavy_io), (2, 8))
        self.assertEqual((selected.upload_receive_timeout_seconds, selected.upload_receive_idle_timeout_seconds), (900, 45))
        for overrides in (
            {"max_concurrent_uploads": 0}, {"max_concurrent_heavy_io": 97},
            {"max_concurrent_uploads": 2, "max_concurrent_heavy_io": 1},
            {"upload_receive_timeout_seconds": float("inf")}, {"upload_receive_idle_timeout_seconds": 0},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                Settings(**(base.model_dump() | overrides))
        for name, raw in (("MAX_CONCURRENT_HEAVY_IO", "97"), ("MAX_CONCURRENT_UPLOADS", "65"),
                          ("UPLOAD_RECEIVE_TIMEOUT_SECONDS", "inf"), ("UPLOAD_RECEIVE_IDLE_TIMEOUT_SECONDS", "0")):
            with self.subTest(name=name), patch.dict(os.environ, valid_environment() | {name: raw}, clear=True):
                with self.assertRaisesRegex(RuntimeError, name):
                    load_settings()

    def test_loads_module_contract(self) -> None:
        with patch.dict(os.environ, valid_environment(), clear=True):
            settings = load_settings()

        self.assertEqual(settings.eneo_backend_url, "http://backend:8000")
        self.assertEqual(settings.module_key, "speech-to-text")
        self.assertEqual(settings.eneo_api_key_header_name, "X-API-Key")
        self.assertTrue(settings.cookie_secure)

    def test_eneo_public_url_is_always_required(self) -> None:
        environment = valid_environment()
        environment.pop("ENEO_PUBLIC_URL")

        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(RuntimeError, "ENEO_PUBLIC_URL"):
                load_settings()

    def test_at_most_64_files_stream_at_once_by_default_and_it_is_configurable(self) -> None:
        with patch.dict(os.environ, valid_environment(), clear=True):
            self.assertEqual(load_settings().max_concurrent_streams, 64)
        with patch.dict(os.environ, valid_environment() | {"MAX_CONCURRENT_STREAMS": "8"}, clear=True):
            self.assertEqual(load_settings().max_concurrent_streams, 8)

    def test_rejects_an_invalid_stream_limit(self) -> None:
        for raw in ("0", "-1", "many", "2.5", ""):
            with self.subTest(raw=raw), patch.dict(os.environ, valid_environment() | {"MAX_CONCURRENT_STREAMS": raw}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "MAX_CONCURRENT_STREAMS must be an integer greater than zero"):
                    load_settings()

    def test_the_body_limits_default_to_10_mib_and_1_gib(self) -> None:
        with patch.dict(os.environ, valid_environment(), clear=True):
            settings = load_settings()

        self.assertEqual((settings.max_body_bytes, settings.max_upload_bytes), (10 * 1024 * 1024, 1024 * 1024 * 1024))

    def test_the_body_limits_are_configurable(self) -> None:
        environment = valid_environment() | {"MAX_BODY_BYTES": "2048", "MAX_UPLOAD_BYTES": "5000000"}

        with patch.dict(os.environ, environment, clear=True):
            settings = load_settings()

        self.assertEqual((settings.max_body_bytes, settings.max_upload_bytes), (2048, 5_000_000))

    def test_rejects_an_invalid_body_limit(self) -> None:
        for name in ("MAX_BODY_BYTES", "MAX_UPLOAD_BYTES"):
            for raw in ("0", "-5", "ten", "1.5", ""):
                environment = valid_environment() | {name: raw}
                with self.subTest(name=name, raw=raw), patch.dict(os.environ, environment, clear=True):
                    with self.assertRaisesRegex(RuntimeError, f"{name} must be an integer greater than zero"):
                        load_settings()

    def test_the_response_bound_defaults_to_32_mib_and_is_configurable(self) -> None:
        with patch.dict(os.environ, valid_environment(), clear=True):
            self.assertEqual(load_settings().max_response_bytes, 32 * 1024 * 1024)
        with patch.dict(os.environ, valid_environment() | {"MAX_RESPONSE_BYTES": "65536"}, clear=True):
            self.assertEqual(load_settings().max_response_bytes, 65536)

    def test_rejects_an_invalid_response_bound(self) -> None:
        for raw in ("0", "-5", "big", "1.5", ""):
            with self.subTest(raw=raw), patch.dict(os.environ, valid_environment() | {"MAX_RESPONSE_BYTES": raw}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "MAX_RESPONSE_BYTES must be an integer greater than zero"):
                    load_settings()

    def test_home_path_is_where_the_callback_lands_without_a_next(self) -> None:
        with patch.dict(os.environ, valid_environment(), clear=True):
            self.assertEqual(load_settings().home_path, "/")
            self.assertEqual(load_settings(home_path="/flows").home_path, "/flows")

    def test_session_max_age_defaults_to_eight_hours(self) -> None:
        with patch.dict(os.environ, valid_environment(), clear=True):
            settings = load_settings()

        self.assertEqual(settings.session_max_age_seconds, 8 * 60 * 60)

    def test_session_max_age_is_configurable_in_minutes(self) -> None:
        environment = valid_environment()
        environment["SESSION_MAX_AGE_MINUTES"] = "90"

        with patch.dict(os.environ, environment, clear=True):
            settings = load_settings()

        self.assertEqual(settings.session_max_age_seconds, 90 * 60)

    def test_rejects_invalid_session_max_age(self) -> None:
        for raw in ("0", "-5", "eight"):
            environment = valid_environment()
            environment["SESSION_MAX_AGE_MINUTES"] = raw
            with self.subTest(raw=raw):
                with patch.dict(os.environ, environment, clear=True):
                    with self.assertRaisesRegex(RuntimeError, "SESSION_MAX_AGE_MINUTES"):
                        load_settings()

    def test_the_upload_timeout_defaults_to_30_minutes_and_is_configurable(self) -> None:
        with patch.dict(os.environ, valid_environment(), clear=True):
            self.assertEqual(load_settings().upload_proxy_timeout_seconds, 1800.0)
        with patch.dict(os.environ, valid_environment() | {"UPLOAD_PROXY_TIMEOUT_SECONDS": "90.5"}, clear=True):
            self.assertEqual(load_settings().upload_proxy_timeout_seconds, 90.5)

    def test_rejects_an_upload_timeout_that_is_not_a_number_above_zero(self) -> None:
        # Not a ValueError from float(): like every other setting, a RuntimeError that names the variable.
        for raw in ("abc", "", "1m", "0", "-5", "nan", "inf", "-inf"):
            with self.subTest(raw=raw), patch.dict(os.environ, valid_environment() | {"UPLOAD_PROXY_TIMEOUT_SECONDS": raw}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "UPLOAD_PROXY_TIMEOUT_SECONDS must be a number greater than zero"):
                    load_settings()

    def test_rejects_a_service_key_header_the_module_would_overwrite_or_that_frames_the_request(self) -> None:
        # The bearer token is set as Authorization after the key, so a key sent under that name would never arrive.
        for name in ("Authorization", "authorization", "Proxy-Authorization", "Cookie", "Host", "Content-Length", "Transfer-Encoding", "Connection", "TE"):
            with self.subTest(name=name), patch.dict(os.environ, valid_environment() | {"ENEO_API_KEY_HEADER_NAME": name}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "ENEO_API_KEY_HEADER_NAME .*credential or framing"):
                    load_settings()

    def test_settings_built_by_a_module_refuse_the_same_service_key_headers(self) -> None:
        # The invariant is the model's, not the environment loader's: create_app takes the settings a module built.
        fields = dict(
            eneo_backend_url="http://eneo.test", eneo_public_url="http://eneo.example", module_public_url="http://module.test",
            module_key="m", eneo_api_key="k", session_secret="x" * 48,
        )
        for name in ("Authorization", "cookie", "Host", "Transfer-Encoding", "not a header", ""):
            with self.subTest(name=name):
                with self.assertRaises(ValueError) as caught:
                    Settings(**fields, eneo_api_key_header_name=name)
                self.assertIn("eneo_api_key_header_name", str(caught.exception))
        for name in ("X-API-Key", "X-Eneo-Module-Key"):
            self.assertEqual(Settings(**fields, eneo_api_key_header_name=name).eneo_api_key_header_name, name)

    def test_the_default_and_a_custom_service_key_header_are_accepted(self) -> None:
        for name in ("X-API-Key", "x-api-key", "X-Eneo-Module-Key"):
            with self.subTest(name=name), patch.dict(os.environ, valid_environment() | {"ENEO_API_KEY_HEADER_NAME": name}, clear=True):
                self.assertEqual(load_settings().eneo_api_key_header_name, name)

    def test_loads_custom_api_key_header_name(self) -> None:
        environment = valid_environment()
        environment["ENEO_API_KEY_HEADER_NAME"] = "X-Eneo-Module-Key"

        with patch.dict(os.environ, environment, clear=True):
            settings = load_settings()

        self.assertEqual(settings.eneo_api_key_header_name, "X-Eneo-Module-Key")

    def test_rejects_invalid_api_key_header_name(self) -> None:
        environment = valid_environment()
        environment["ENEO_API_KEY_HEADER_NAME"] = "X-API-Key: injected"

        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(RuntimeError, "valid HTTP header"):
                load_settings()

    def test_rejects_unstable_module_key(self) -> None:
        environment = valid_environment()
        environment["MODULE_KEY"] = "Speech To Text"

        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(RuntimeError, "lowercase kebab-case"):
                load_settings()

    def test_rejects_public_url_with_query_string(self) -> None:
        environment = valid_environment()
        environment["MODULE_PUBLIC_URL"] = "https://module.example.test?ticket=bad"

        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(RuntimeError, "query string or fragment"):
                load_settings()

    def test_a_bare_question_mark_or_hash_is_a_query_or_fragment_too(self) -> None:
        for name in ("MODULE_PUBLIC_URL", "ENEO_BACKEND_URL", "ENEO_PUBLIC_URL"):
            for suffix in ("?", "#", "/?", "/#"):
                environment = valid_environment()
                environment[name] = environment[name] + suffix
                with self.subTest(name=name, suffix=suffix), patch.dict(os.environ, environment, clear=True):
                    with self.assertRaisesRegex(RuntimeError, "query string or fragment"):
                        load_settings()

    def test_the_modules_origin_is_in_canonical_form(self) -> None:
        for public_url, origin in (
            ("https://module.example.test", "https://module.example.test"),
            ("https://Mod.Example.SE", "https://mod.example.se"),
            ("HTTPS://MOD.example.se:443/", "https://mod.example.se"),
            ("http://mod.example.se:80", "http://mod.example.se"),
            ("https://mod.example.se:8443/prefix", "https://mod.example.se:8443"),
            ("http://[::1]:3001", "http://[::1]:3001"),
            ("http://LOCALHOST:3001", "http://localhost:3001"),
        ):
            environment = valid_environment() | {"MODULE_PUBLIC_URL": public_url}
            with self.subTest(public_url=public_url), patch.dict(os.environ, environment, clear=True):
                self.assertEqual(load_settings().module_origin, origin)

    def test_canonical_origin_of_what_a_browser_sends(self) -> None:
        for sent, origin in (
            ("https://mod.example.se", "https://mod.example.se"),
            ("https://MOD.example.se:443", "https://mod.example.se"),
            ("https://mod.example.se:8443", "https://mod.example.se:8443"),
        ):
            with self.subTest(sent=sent):
                self.assertEqual(canonical_origin(sent, origin_only=True), origin)
        for sent in ("", "null", "mod.example.se", "ftp://mod.example.se", "https://", "https://x:notaport",
                     "https://mod.example.se/", "https://mod.example.se/evil", "https://mod.example.se?x", "https://u:p@mod.example.se"):
            with self.subTest(sent=sent):
                self.assertIsNone(canonical_origin(sent, origin_only=True))

    def test_rejects_ambiguous_cookie_secure_value(self) -> None:
        environment = valid_environment()
        environment["COOKIE_SECURE"] = "truthy"

        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(RuntimeError, "must be a boolean"):
                load_settings()


class OrganizationTests(unittest.TestCase):
    """The organisation beside "Tal till text", set per deployment."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def file(self, name: str, content: bytes) -> str:
        path = self.folder / name
        path.write_bytes(content)
        return str(path)

    def load(self, default: Organization | None = None, **overrides: str):
        environment = valid_environment() | overrides
        with patch.dict(os.environ, environment, clear=True):
            return load_settings(default_organization=default)

    def test_the_default_is_sundsvall_with_its_bundled_logo(self) -> None:
        settings = self.load(default=SUNDSVALL)
        self.assertEqual(settings.organization, Organization(name="Sundsvalls kommun", logo="default"))
        self.assertIsNone(settings.organization_logo)

    def test_with_no_organisation_variables_and_no_default_there_is_no_organisation(self) -> None:
        settings = self.load()
        self.assertIsNone(settings.organization)
        self.assertIsNone(settings.organization_logo)
        self.assertIsNone(settings.organization_logo_dark)

    def test_another_organisation_mounts_its_own_logo_and_names_itself(self) -> None:
        settings = self.load(
            ORGANIZATION_NAME="Umeå kommun",
            ORGANIZATION_LOGO=self.file("umea.svg", SVG),
            ORGANIZATION_LOGO_DARK=self.file("umea-dark.png", PNG),
        )
        self.assertEqual(settings.organization, Organization(name="Umeå kommun", logo="custom", dark_logo=True))
        assert settings.organization_logo and settings.organization_logo_dark
        self.assertEqual(settings.organization_logo.media_type, "image/svg+xml")
        self.assertEqual(settings.organization_logo.content, SVG)
        self.assertEqual(settings.organization_logo_dark.media_type, "image/png")

    def test_a_name_without_a_logo_shows_the_name_never_sundsvalls_logo(self) -> None:
        settings = self.load(ORGANIZATION_NAME="Region Västernorrland")
        self.assertEqual(settings.organization, Organization(name="Region Västernorrland", logo=None))

    def test_the_organisation_can_be_hidden_leaving_the_product_name(self) -> None:
        settings = self.load(SHOW_ORGANIZATION="false", ORGANIZATION_LOGO=self.file("logo.svg", SVG))
        self.assertIsNone(settings.organization)
        self.assertIsNone(settings.organization_logo)

    def test_a_missing_logo_says_so_once_and_the_name_stands_in(self) -> None:
        with self.assertLogs("eneo_config", level="ERROR") as logs:
            settings = self.load(ORGANIZATION_NAME="Umeå kommun", ORGANIZATION_LOGO=str(self.folder / "saknas.svg"))
        self.assertEqual(settings.organization, Organization(name="Umeå kommun", logo=None))
        self.assertEqual(len(logs.output), 1)
        self.assertIn("ORGANIZATION_LOGO", logs.output[0])

    def test_only_svg_and_png_are_logos(self) -> None:
        for name, content in (
            ("logo.gif", b"GIF89a" + b"\x00" * 16),
            ("logo.svg", PNG),  # the name says SVG, the content does not
            ("logo.png", b"<html><script>alert(1)</script></html>"),
        ):
            with self.subTest(name=name), self.assertLogs("eneo_config", level="ERROR"):
                settings = self.load(ORGANIZATION_NAME="Umeå kommun", ORGANIZATION_LOGO=self.file(name, content))
            self.assertEqual(settings.organization, Organization(name="Umeå kommun", logo=None))

    def test_a_large_file_is_refused_without_reading_it_whole(self) -> None:
        big = self.file("logo.svg", b'<svg xmlns="http://www.w3.org/2000/svg">' + b" " * (3 * 2**20) + b"</svg>")
        reads: list[int] = []
        real_open = Path.open

        def spying_open(path: Path, *args, **kwargs):
            handle = real_open(path, *args, **kwargs)
            if str(path) != big:
                return handle
            real_read = handle.read

            def read(size: int = -1) -> bytes:
                reads.append(size)
                return real_read(size)

            handle.read = read  # type: ignore[method-assign]
            return handle

        with patch.object(Path, "open", spying_open), self.assertLogs("eneo_config", level="ERROR") as logs:
            settings = self.load(ORGANIZATION_NAME="Umeå kommun", ORGANIZATION_LOGO=big)
        self.assertEqual(settings.organization, Organization(name="Umeå kommun", logo=None))
        self.assertIn("larger than 1 MiB", logs.output[0])
        self.assertEqual(reads, [2**20 + 1], "the read stops one byte past the limit")

    def test_a_missing_dark_logo_keeps_the_light_one(self) -> None:
        with self.assertLogs("eneo_config", level="ERROR"):
            settings = self.load(
                ORGANIZATION_NAME="Umeå kommun",
                ORGANIZATION_LOGO=self.file("umea.svg", SVG),
                ORGANIZATION_LOGO_DARK=str(self.folder / "saknas.svg"),
            )
        self.assertEqual(settings.organization, Organization(name="Umeå kommun", logo="custom", dark_logo=False))

    def test_a_logo_needs_the_name_it_stands_for(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "ORGANIZATION_NAME"):
            self.load(ORGANIZATION_LOGO=self.file("logo.svg", SVG))

    def test_rejects_an_ambiguous_show_organization(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "SHOW_ORGANIZATION must be a boolean"):
            self.load(SHOW_ORGANIZATION="kanske")


if __name__ == "__main__":
    unittest.main()
