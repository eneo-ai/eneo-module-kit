"""The Eneo module contract for a FastAPI BFF."""

from .app import create_app
from .auth import ModuleSession, ModuleUser
from .deps import require_same_origin, require_session, upstream_auth_headers
from .proxy import RESOURCE_ID, ProxyRule, rule
from .serve import serve
from .settings import Organization, Settings, load_settings
from .transport import forward_upload, stream_signed

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "create_app",
    "serve",
    "Settings",
    "Organization",
    "load_settings",
    "ModuleSession",
    "ModuleUser",
    "ProxyRule",
    "rule",
    "RESOURCE_ID",
    "require_session",
    "require_same_origin",
    "upstream_auth_headers",
    "forward_upload",
    "stream_signed",
]
