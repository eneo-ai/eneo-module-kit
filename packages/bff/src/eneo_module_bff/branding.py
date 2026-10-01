from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response

# The organisation beside the product name is a deployment setting (Settings.organization). Neither
# route asks for a session: the login page shows the organisation before there is one.

router = APIRouter()


@router.get("/api/branding")
async def get_branding(request: Request):
    return {"organization": request.app.state.settings.organization}


@router.get("/api/branding/logo/{variant}")
async def get_branding_logo(request: Request, variant: Literal["light", "dark"]) -> Response:
    settings = request.app.state.settings
    logo = settings.organization_logo if variant == "light" else settings.organization_logo_dark
    if logo is None:
        raise HTTPException(status_code=404, detail="No logo is configured")
    return Response(
        content=logo.content,
        media_type=logo.media_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            # Revalidate every time: a replaced logo shows after the restart that loads it.
            "Cache-Control": "no-cache",
            # An SVG opened on its own, not through <img>, must run nothing in the module's origin.
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
        },
    )
