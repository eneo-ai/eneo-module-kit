from __future__ import annotations

import logging
import math
import os
import re
import unicodedata
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel


logger = logging.getLogger("eneo_config")

# The headers that carry credentials or frame a request. A module cannot add one to the request headers the proxy
# forwards (proxy.py), and none can be the name of the service key's header: the module sets Authorization from the
# session after the key, and the others are the HTTP client's to write.
CREDENTIAL_AND_FRAMING_HEADERS = frozenset(
    {
        "authorization",
        "cookie",
        "origin",
        "referer",
        "x-api-key",
        "proxy-authorization",
        "host",
        "content-length",
        "transfer-encoding",
        "connection",
        "keep-alive",
        "te",
        "trailer",
        "upgrade",
    }
)


class Organization(BaseModel):
    """The organisation shown beside the product name: its name, and its logo.

    ``logo`` is ``default`` for the logo the module bundles in its own frontend (the kit serves no file for it),
    ``custom`` for the deployment's own (served by /api/branding/logo/{light,dark}), or None for the name as text.
    """

    name: str
    logo: Literal["default", "custom"] | None
    dark_logo: bool = False


class LogoFile(BaseModel):
    media_type: Literal["image/svg+xml", "image/png"]
    content: bytes


_LOGO_MAX_BYTES = 1024 * 1024


class Settings(BaseModel):
    eneo_backend_url: str
    eneo_public_url: str
    module_public_url: str
    module_key: str
    eneo_api_key: str
    eneo_api_key_header_name: str = "X-API-Key"
    session_secret: str
    cookie_secure: bool = True
    upload_proxy_timeout_seconds: float = 1800.0
    # The most of any request body the module reads (limits.py), whatever the content type, but an upload that
    # forward_upload reads.
    max_body_bytes: int = 10 * 1024 * 1024
    # The most one upload may declare (forward_upload).
    max_upload_bytes: int = 1024 * 1024 * 1024
    # How many files may stream at once (stream_signed). The shared client keeps 100 connections, and a file holds
    # one for as long as it streams: this leaves the rest for the API.
    max_concurrent_streams: int = 64
    # Övre gräns för modulsessionen. Den slutar senast vid
    # Eneos sessionstak (module_auth_max_session_hours); modultoken förnyas
    # via Eneo fram till dess.
    session_max_age_seconds: int = 8 * 60 * 60
    # Where the callback lands when no `next` is given.
    home_path: str = "/"
    # None shows the product name alone (no default organisation, or SHOW_ORGANIZATION=false).
    organization: Organization | None = None
    organization_logo: LogoFile | None = None
    organization_logo_dark: LogoFile | None = None

    @property
    def module_origin(self) -> str:
        """The module's origin in canonical form, the one an ``Origin`` header is compared with."""
        origin = canonical_origin(self.module_public_url)
        if origin is None:
            raise ValueError("module_public_url must be an absolute http(s) URL")
        return origin


def has_control_character(value: str | None) -> bool:
    """A control character (C0, DEL, C1) or a line or paragraph separator: none belongs in a file name, a media type
    or a path that a browser or a URL parser will read."""
    return value is not None and any(unicodedata.category(character) in {"Cc", "Zl", "Zp"} for character in value)


_DEFAULT_PORTS = {"http": 80, "https": 443}


def canonical_origin(url: str, *, origin_only: bool = False) -> str | None:
    """``scheme://host[:port]`` of an absolute http(s) URL, or None if ``url`` is not one.

    Scheme and host are lower case and a default port is left out, which is how a browser writes an ``Origin``,
    so ``https://Mod.Example.SE:443/prefix`` and ``https://mod.example.se`` are the same origin. With
    ``origin_only`` anything but an origin (a path, a query, a fragment, a user) is None: that is what an
    ``Origin`` header holds, and nothing else is one.
    """
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return None
    host = parsed.hostname
    if parsed.scheme.lower() not in _DEFAULT_PORTS or not host:
        return None
    if origin_only and (parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password):
        return None
    scheme = parsed.scheme.lower()
    if ":" in host:
        host = f"[{host}]"
    return f"{scheme}://{host}" + ("" if port in (None, _DEFAULT_PORTS[scheme]) else f":{port}")


def _parse_bool(raw: str | None, *, default: bool, name: str) -> bool:
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean")


def _read_logo(variable: str, raw_path: str) -> LogoFile | None:
    """The logo file at ``raw_path`` if it is an SVG or a PNG, as its name says; otherwise logs why and gives None."""
    path = Path(raw_path)
    try:
        # Read at most one byte past the limit, so a large file mounted by mistake is never loaded whole.
        with path.open("rb") as file:
            content = file.read(_LOGO_MAX_BYTES + 1)
    except OSError as error:
        logger.error("%s=%s cannot be read (%s); the organisation's name is shown instead.", variable, raw_path, error.strerror)
        return None
    head = content[:1024].lstrip(b"\xef\xbb\xbf \t\r\n")
    suffix = path.suffix.lower()
    if len(content) > _LOGO_MAX_BYTES:
        problem = "is larger than 1 MiB"
    elif suffix == ".png" and content.startswith(b"\x89PNG\r\n\x1a\n"):
        return LogoFile(media_type="image/png", content=content)
    elif suffix == ".svg" and head.startswith((b"<?xml", b"<svg", b"<!--", b"<!DOCTYPE")) and re.search(rb"<svg[\s>]", head):
        return LogoFile(media_type="image/svg+xml", content=content)
    else:
        problem = "is not an SVG or PNG file (by its name and its content)"
    logger.error("%s=%s %s; the organisation's name is shown instead.", variable, raw_path, problem)
    return None


def _organization(
    default_organization: Organization | None,
) -> tuple[Organization | None, LogoFile | None, LogoFile | None]:
    """The organisation shown beside the product name, from ORGANIZATION_* and SHOW_ORGANIZATION.

    With none of them set it is ``default_organization`` (the module's own, if it has one). A name alone is
    shown as text, never beside the default's logo. A logo that cannot be used is
    logged once at start and the name stands in for it.
    """
    if not _parse_bool(os.environ.get("SHOW_ORGANIZATION"), default=True, name="SHOW_ORGANIZATION"):
        return None, None, None
    name = " ".join((os.environ.get("ORGANIZATION_NAME") or "").split())
    logo_path = os.environ.get("ORGANIZATION_LOGO") or None
    dark_path = os.environ.get("ORGANIZATION_LOGO_DARK") or None
    if len(name) > 100:
        raise RuntimeError("ORGANIZATION_NAME must be at most 100 characters")
    if not name:
        if logo_path or dark_path:
            raise RuntimeError("ORGANIZATION_LOGO needs ORGANIZATION_NAME: the name is the logo's text alternative")
        return default_organization, None, None
    logo = _read_logo("ORGANIZATION_LOGO", logo_path) if logo_path else None
    if logo is None:
        return Organization(name=name, logo=None), None, None
    dark = _read_logo("ORGANIZATION_LOGO_DARK", dark_path) if dark_path else None
    return Organization(name=name, logo="custom", dark_logo=dark is not None), logo, dark


def _required_url(name: str) -> str:
    value = os.environ[name].rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(f"{name} must be an absolute http(s) URL")
    # urlsplit reads a bare ? or # as an empty query or fragment, which is still one.
    if parsed.query or parsed.fragment or "?" in value or "#" in value:
        raise RuntimeError(f"{name} must not contain a query string or fragment")
    return value


def _positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value <= 0:
        raise RuntimeError(f"{name} must be an integer greater than zero")
    return value


def _positive_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        value = 0.0
    # nan compares false with everything and inf is no budget: neither is a number of seconds.
    if not (math.isfinite(value) and value > 0):
        raise RuntimeError(f"{name} must be a number greater than zero")
    return value


def load_settings(*, default_organization: Organization | None = None, home_path: str = "/") -> Settings:
    required = [
        "ENEO_BACKEND_URL",
        "MODULE_PUBLIC_URL",
        "MODULE_KEY",
        "ENEO_API_KEY",
        "SESSION_SECRET",
        "ENEO_PUBLIC_URL",
    ]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}"
        )

    session_secret = os.environ["SESSION_SECRET"]
    if len(session_secret) < 32:
        raise RuntimeError("SESSION_SECRET must be at least 32 characters")

    module_key = os.environ["MODULE_KEY"]
    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", module_key) is None:
        raise RuntimeError("MODULE_KEY must use lowercase kebab-case")

    api_key_header_name = os.environ.get("ENEO_API_KEY_HEADER_NAME", "X-API-Key")
    if re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", api_key_header_name) is None:
        raise RuntimeError("ENEO_API_KEY_HEADER_NAME must be a valid HTTP header name")
    # X-API-Key is the default name, so it is the one entry of the set that is allowed.
    if api_key_header_name.lower() in CREDENTIAL_AND_FRAMING_HEADERS - {"x-api-key"}:
        raise RuntimeError(f"ENEO_API_KEY_HEADER_NAME cannot be a credential or framing header ({api_key_header_name})")

    raw_session_minutes = os.environ.get("SESSION_MAX_AGE_MINUTES", "480")
    try:
        session_minutes = int(raw_session_minutes)
    except ValueError:
        raise RuntimeError("SESSION_MAX_AGE_MINUTES must be an integer") from None
    if session_minutes <= 0:
        raise RuntimeError("SESSION_MAX_AGE_MINUTES must be greater than zero")

    organization, organization_logo, organization_logo_dark = _organization(default_organization)

    return Settings(
        eneo_backend_url=_required_url("ENEO_BACKEND_URL"),
        eneo_public_url=_required_url("ENEO_PUBLIC_URL"),
        module_public_url=_required_url("MODULE_PUBLIC_URL"),
        module_key=module_key,
        eneo_api_key=os.environ["ENEO_API_KEY"],
        eneo_api_key_header_name=api_key_header_name,
        session_secret=session_secret,
        cookie_secure=_parse_bool(os.environ.get("COOKIE_SECURE"), default=True, name="COOKIE_SECURE"),
        upload_proxy_timeout_seconds=_positive_float("UPLOAD_PROXY_TIMEOUT_SECONDS", 1800.0),
        max_body_bytes=_positive_int("MAX_BODY_BYTES", 10 * 1024 * 1024),
        max_upload_bytes=_positive_int("MAX_UPLOAD_BYTES", 1024 * 1024 * 1024),
        max_concurrent_streams=_positive_int("MAX_CONCURRENT_STREAMS", 64),
        session_max_age_seconds=session_minutes * 60,
        home_path=home_path,
        organization=organization,
        organization_logo=organization_logo,
        organization_logo_dark=organization_logo_dark,
    )
