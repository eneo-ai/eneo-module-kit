"""This module's own API routes. Add yours to ``router``.

Every route needs ``Depends(require_session)``, and a route that writes also needs ``Depends(require_same_origin)``
(see ``tests/test_routes.py``: it fails when one is missing). Call Eneo from a route with
``upstream_auth_headers(request)``, which holds the service key and the user's token; for an upload or a file, the
kit's ``forward_upload`` and ``stream_signed``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from eneo_module_bff import ModuleSession, require_session

router = APIRouter()


@router.get("/api/example")
async def example(session: Annotated[ModuleSession, Depends(require_session)]) -> dict[str, str]:
    """The smallest route of a module: it knows who is signed in. Replace it."""
    return {"greeting": f"Hej {session.user.username or session.user.email}"}
