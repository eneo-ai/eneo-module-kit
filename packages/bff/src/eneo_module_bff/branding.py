from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response

from .accent import etag, theme_css

# The login page shows the organisation and its theme before there is a session.

router = APIRouter()


def _etag_matches(if_none_match: str | None, current: str) -> bool:
    if if_none_match is None:
        return False
    listed = {value.strip().removeprefix("W/") for value in if_none_match.split(",")}
    return "*" in listed or current in listed


@router.get("/api/branding/theme.css")
async def get_branding_theme(request: Request) -> Response:
    css = theme_css(request.app.state.settings.accent)
    headers = {
        "Cache-Control": "public, max-age=300",
        "ETag": etag(css),
        "X-Content-Type-Options": "nosniff",
    }
    if _etag_matches(request.headers.get("if-none-match"), headers["ETag"]):
        return Response(status_code=304, headers=headers)
    return Response(content=css, media_type="text/css", headers=headers)


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
