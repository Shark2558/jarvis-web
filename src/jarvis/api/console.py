# src/jarvis/api/console.py
"""The browser console (Layer 1: web surface). One static page served by the API itself —
one deployable, one URL. Phase 6 replaces it with the Next.js / React Native clients against
the same /v1 contract."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from jarvis.api.auth import session_email
from jarvis.config import Settings

router = APIRouter()
_STATIC = Path(__file__).parent / "static"


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
                "default-src 'none'; script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; "
                "font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
            ),
        },
    )


@router.get("/console/config", include_in_schema=False)
async def console_config(s: Settings = Depends(_settings)) -> dict[str, str]:
    """Non-sensitive: tells the page which sign-in flow to show."""
    return {"auth_mode": s.auth_mode.value, "honorific": s.user_honorific}


@router.get("/auth/me")
async def me(request: Request, s: Settings = Depends(_settings)) -> dict[str, str]:
    email = session_email(request, s)
    if email is None:
        raise HTTPException(401, "not signed in")
    return {"email": email}
