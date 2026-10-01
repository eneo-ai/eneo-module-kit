from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel


logger = logging.getLogger("eneo_config")


class Organization(BaseModel):
    """The organisation beside "Tal till text": its name, and its logo.

    ``logo`` is ``default`` for Sundsvall's bundled logo, ``custom`` for the
    deployment's own (served by /api/branding/logo/{light,dark}), or None for
    the name as text.
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
        parsed = urlsplit(self.module_public_url)
        return f"{parsed.scheme}://{parsed.netloc}"


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
    if parsed.query or parsed.fragment:
        raise RuntimeError(f"{name} must not contain a query string or fragment")
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

    upload_timeout = float(os.environ.get("UPLOAD_PROXY_TIMEOUT_SECONDS", "1800"))
    if upload_timeout <= 0:
        raise RuntimeError("UPLOAD_PROXY_TIMEOUT_SECONDS must be greater than zero")

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
        upload_proxy_timeout_seconds=upload_timeout,
        session_max_age_seconds=session_minutes * 60,
        home_path=home_path,
        organization=organization,
        organization_logo=organization_logo,
        organization_logo_dark=organization_logo_dark,
    )
