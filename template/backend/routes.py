"""This module's own API routes. Add yours to ``router``.

Every route needs ``Depends(require_session)``, and a route that writes also needs ``Depends(require_same_origin)`` and
``Depends(require_expected_user)``: the page names its user on a write (``fetchWithSession`` does), so a page under
someone else's session cannot write as them (see ``tests/test_routes.py``: it fails when one is missing). For example:

    @router.post("/api/notes", dependencies=[Depends(require_session), Depends(require_same_origin), Depends(require_expected_user)])

Call Eneo from a route with ``upstream_auth_headers(request)``, which holds the service key and the user's token; for
an upload or a file, the kit's ``forward_upload`` and ``stream_signed``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from eneo_module_bff import ModuleSession, require_session

router = APIRouter()


@router.get("/api/example")
async def example(session: Annotated[ModuleSession, Depends(require_session)]) -> dict[str, str]:
    """The smallest route of a module: it knows who is signed in. Replace it."""
    return {"greeting": f"Hej {session.user.username or session.user.email}"}
