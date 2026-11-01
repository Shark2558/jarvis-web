# src/jarvis/api/console.py
"""The browser console (Layer 1: web surface). One static page served by the API itself —
one deployable, one URL. Phase 6 replaces it with the Next.js / React Native clients against
the same /v1 contract."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from jarvis.api.auth import session_email
from jarvis.config import Settings

router = APIRouter()
_STATIC = Path(__file__).parent / "static"
_FONTS = _STATIC / "fonts"
# Self-hosted OFL fonts (licences beside them). Only these exact names are ever served: the
# route never builds a path from user input that is not in this set, so traversal is impossible.
FONT_FILES = frozenset(
    {
        "orbitron-latin-600-normal.woff2",
        "orbitron-latin-700-normal.woff2",
        "rajdhani-latin-500-normal.woff2",
        "rajdhani-latin-600-normal.woff2",
        "rajdhani-latin-700-normal.woff2",
    }
)
_FONT_CACHE = "public, max-age=31536000, immutable"


def _settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


@router.get("/", include_in_schema=False, response_class=HTMLResponse)
async def console() -> HTMLResponse:
    html = (_STATIC / "console.html").read_text(encoding="utf-8")
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": (
                "default-src 'none'; script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; "
                "font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
            ),
        },
    )


def _script(name: str) -> FileResponse:
    return FileResponse(
        _STATIC / name,
        media_type="application/javascript",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/static/console.js", include_in_schema=False)
async def console_js() -> FileResponse:
    return _script("console.js")


@router.get("/static/console-fx.js", include_in_schema=False)
async def console_fx_js() -> FileResponse:
    """Theme engine, background field and the Core emblem (split out to keep console.js lean)."""
    return _script("console-fx.js")


@router.get("/static/fonts/{name}", include_in_schema=False)
async def console_font(name: str) -> FileResponse:
    if name not in FONT_FILES:
        raise HTTPException(404, "not found")
    return FileResponse(
        _FONTS / name,
        media_type="font/woff2",
        headers={"Cache-Control": _FONT_CACHE, "X-Content-Type-Options": "nosniff"},
    )


@router.get("/console/config", include_in_schema=False)
async def console_config(s: Settings = Depends(_settings)) -> dict[str, str]:
    """Non-sensitive: tells the page which sign-in flow to show."""
    warning = (
        "Free Gemini brain: Google may use what you type here to improve its products. "
        "Do not share private or confidential information."
        if s.llm_trains_on_content
        else ""
    )
    return {
        "auth_mode": s.auth_mode.value,
        "honorific": s.user_honorific,
        "brain": s.llm_backend.value,
        "privacy_warning": warning,
    }


@router.get("/auth/me")
async def me(request: Request, s: Settings = Depends(_settings)) -> dict[str, str]:
    email = session_email(request, s)
    if email is None:
        raise HTTPException(401, "not signed in")
    return {"email": email}
