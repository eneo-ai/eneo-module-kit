from typing import Annotated
from fastapi import Cookie
from fastapi.requests import HTTPConnection
from .auth import SESSION_COOKIE, ModuleAuth, ModuleSession


def _auth(connection: HTTPConnection) -> ModuleAuth:
    return connection.app.state.module_auth


async def require_session(
    connection: HTTPConnection,
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> ModuleSession:
    """The caller's live session; 401 with X-Auth-Required for a request, a refused handshake for a WebSocket."""
    return await _auth(connection).require_session(connection, session_id)


def require_same_origin(connection: HTTPConnection) -> None:
    """Writes and WebSocket handshakes only from the module's own origin."""
    _auth(connection).require_same_origin(connection)


def upstream_auth_headers(connection: HTTPConnection) -> dict[str, str]:
    """The service key and the caller's module-user token, for a call to Eneo."""
    return _auth(connection).upstream_auth_headers(connection)
