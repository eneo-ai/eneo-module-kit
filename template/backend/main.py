"""The module's backend: the kit's BFF with this module's routes and its allowlist of Eneo routes.

Run it with ``python -c "from eneo_module_bff import serve; serve('main:build_app', factory=True)"`` (the image does).
Its settings are environment variables (``.env.example`` names them all).
"""

import os
from pathlib import Path

import httpx2
from fastapi import FastAPI

from eneo_module_bff import Settings, create_app, rule
from routes import router

# The built UI. In the image STATIC_DIR points at it; beside the source it is web/dist.
STATIC_DIR = Path(os.environ.get("STATIC_DIR") or Path(__file__).resolve().parent.parent / "web" / "dist")

# The Eneo routes this module may call through the proxy at /api/eneo/<path>, and nothing else: add one rule per
# route, with the methods it needs. ``rule("GET", r"flows/$")`` allows GET /api/eneo/flows/, which goes to Eneo's
# /api/v1/flows/. Patterns are matched against the whole path; RESOURCE_ID matches one id segment.
PROXY_RULES = [
    rule("GET", r"flows/$"),
]


def build_app(
    settings: Settings | None = None,
    *,
    static_dir: Path = STATIC_DIR,
    http_client: httpx2.AsyncClient | None = None,
) -> FastAPI:
    """The app; with no ``settings`` it reads them from the environment. Tests pass their own."""
    return create_app(
        settings,
        title="Eneo-modul",
        routers=[router],
        proxy_rules=PROXY_RULES,
        static_dir=static_dir,
        http_client=http_client,
    )
