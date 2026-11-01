# src/jarvis/api/console.py
"""The browser console (Layer 1: web surface). One static page served by the API itself —
one deployable, one URL. Phase 6 replaces it with the Next.js / React Native clients against
the same /v1 contract."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from jarvis.api.auth import session_email
from jarvis.config import Settings

router = APIRouter()
_STATIC = Path(__file__).parent / "static"
_FONTS = _STATIC / "fonts"
_VENDOR = _STATIC / "vendor"
_JS = "application/javascript"
_IMMUTABLE = "public, max-age=31536000, immutable"

# Every URL below is an exact allow-list: no route ever builds a path from request input that
# is not one of these literal names, so traversal is impossible by construction.

# The console's own code and styles. They change with every deploy and carry no version in
# their URL, so they are never cached.
APP_ASSETS: dict[str, str] = {
    "console.js": _JS,
    "console-fx.js": _JS,  # theme engine, surfaces, background field, 2D Core, appearance menu
    "console-deck.js": _JS,  # Command Deck: panels, dock, rails, radar, vitals
    "console-brief.js": _JS,  # morning Brief panel: today's brief, its settings and confirms
    "console-usage.js": _JS,  # Vitals: this month's AI spend in rupees and the owner's limit
    "console-memory.js": _JS,  # Memory panel: About you, facts, learning consent (slice 8)
    "console-3d.js": _JS,  # three.js scenes (ES module; loads three lazily, 2D fallback)
    "console-3d-scenes.js": _JS,  # Core / Globe / Construct scene builders (ES module)
    "console.css": "text/css",
    "console-deck.css": "text/css",
    "console-memory.css": "text/css",
}

# Self-hosted OFL fonts (licences beside them).
FONT_FILES = frozenset(
    {
        "orbitron-latin-600-normal.woff2",
        "orbitron-latin-700-normal.woff2",
        "rajdhani-latin-500-normal.woff2",
        "rajdhani-latin-600-normal.woff2",
        "rajdhani-latin-700-normal.woff2",
        "share-tech-mono-latin-400-normal.woff2",
    }
)

# Vendored three.js (MIT, LICENSE-three.txt beside it). The release is part of the URL, so the
# year-long immutable cache can never serve a stale library after an upgrade.
THREE_RELEASE = "three-0.187.0"
VENDOR_FILES = frozenset({"three.module.min.js"})


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


def _asset_endpoint(name: str, media_type: str) -> Callable[[], Awaitable[FileResponse]]:
    async def serve() -> FileResponse:
        return FileResponse(
            _STATIC / name,
            media_type=media_type,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    serve.__name__ = "console_asset_" + name.replace(".", "_").replace("-", "_")
    return serve


# One literal route per asset (not a `/static/{name}` catch-all, which would also make Starlette
# answer `/static/fonts/` with a slash redirect instead of a plain 404).
for _name, _type in APP_ASSETS.items():
    router.add_api_route(
        f"/static/{_name}",
        _asset_endpoint(_name, _type),
        methods=["GET"],
        include_in_schema=False,
    )


@router.get("/static/fonts/{name}", include_in_schema=False)
async def console_font(name: str) -> FileResponse:
    if name not in FONT_FILES:
        raise HTTPException(404, "not found")
    return FileResponse(
        _FONTS / name,
        media_type="font/woff2",
        headers={"Cache-Control": _IMMUTABLE, "X-Content-Type-Options": "nosniff"},
    )


@router.get("/static/vendor/{release}/{name}", include_in_schema=False)
async def console_vendor(release: str, name: str) -> FileResponse:
    if release != THREE_RELEASE or name not in VENDOR_FILES:
        raise HTTPException(404, "not found")
    return FileResponse(
        _VENDOR / name,
        media_type=_JS,
        headers={"Cache-Control": _IMMUTABLE, "X-Content-Type-Options": "nosniff"},
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
