from typing import Annotated

import httpx2
from fastapi import Cookie, Depends
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


async def require_expected_user(
    connection: HTTPConnection, session: Annotated[ModuleSession, Depends(require_session)]
) -> None:
    """409 ``user_changed`` unless the page names the session's user in ``X-Expected-User``: a write must, and a read
    that names someone must name them. A WebSocket handshake is refused: a browser cannot set the header on one, so a
    WebSocket route does not use this. Runs ``require_session`` first."""
    _auth(connection).require_expected_user(connection, session)


def upstream_auth_headers(connection: HTTPConnection) -> dict[str, str]:
    """The service key and the caller's module-user token, for a call to Eneo."""
    return _auth(connection).upstream_auth_headers(connection)


async def raise_if_session_ended(connection: HTTPConnection, answer: httpx2.Response) -> None:
    """Call it with Eneo's ``answer`` to a call made with ``upstream_auth_headers``: when Eneo confirms that the user's
    login is over, the session ends and the caller gets the kit's answer for an ended session (401 with
    ``X-Auth-Required: session``; a socket, accepted or not, is closed with 1008). Otherwise it returns, and the route
    handles ``answer`` as before. The answer must have been read (not ``stream=True``), or it is a RuntimeError."""
    await _auth(connection).raise_if_session_ended(connection, answer)
