# src/jarvis/api/app_shell.py
"""R7 Part A, the app on the web side (docs/plans/r7-mobile.md D3, D8, D15, D21): the part's one
join with the app (`build(ctx) -> MobilePart`, `jarvis.mobile.ports`) and its routes.

    GET  /manifest.webmanifest   the web app manifest (static/manifest.webmanifest): public, no
                                 cookie; without `app_share_enabled` it has no share target
    GET  /static/icons/<name>    the icons scripts/app_icons.py drew (an exact allow-list)
    GET  /app/share/sw.js        the share tray's worker (static/app-share-sw.js), scope
                                 /app/share/ only: it controls no page; the console's CSP
    POST /app/share/in           reached only when that worker was not installed yet: the body
                                 is discarded UNREAD and the page says "Open JARVIS once, then
                                 share again." (a GET goes to the console)
    GET  /app/status             owner-only: {part, ready, share}

Every public route here is on D21's never-locked list (`/manifest.webmanifest`, `/static/*`,
`/app/share/*`), so a locked app can still install, update and take a share. With
`mobile_enabled` off none of them is served (404) and the part says "off". The part gives the
brain no tool and registers one privacy row: shared items wait in this phone's browser only.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from jarvis.api.auth import require_auth
from jarvis.api.console import CONSOLE_CSP
from jarvis.api.mobile_status import NO_STORE, part_of
from jarvis.config import Settings
from jarvis.mobile.ports import NOT_BUILT, MobileContext, MobilePart, PartName
from jarvis.privacy.ports import CategoryView

PART: PartName = "shell"
READY, OFF = "ready", "off"
_STATIC = Path(__file__).parent / "static"
MANIFEST_PATH = "/manifest.webmanifest"
MANIFEST_TYPE = "application/manifest+json"
SHARE_SCOPE = "/app/share/"
SHARE_SW_PATH = SHARE_SCOPE + "sw.js"
SHARE_IN_PATH = SHARE_SCOPE + "in"  # the share target's action (= r7_wiring.SHARE_IN_PATH)
SHARE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".pdf"})
# scripts/app_icons.py draws exactly these; nothing else under /static/icons/ is ever served
ICONS: Mapping[str, int] = {
    "jarvis-192.png": 192,
    "jarvis-512.png": 512,
    "jarvis-maskable-512.png": 512,
    "talk-96.png": 96,
    "look-96.png": 96,
    "sos-96.png": 96,
}
MISSED = "Open JARVIS once, then share again."
SHARE_OFF = "Sharing into JARVIS is switched off."
_JS = "application/javascript"
_PAGE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": CONSOLE_CSP,
}
# The console's own gate card (console.css): no script, nothing of the share comes back.
_PAGE = """<!doctype html>
<html lang="en" data-theme="workshop" data-surface="night">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#04070D">
<title>JARVIS</title>
<link rel="stylesheet" href="/static/console.css">
</head>
<body>
<div class="gate show"><main class="gate-card card hud">
<h2>JARVIS</h2>
<p>{words}</p>
<a class="cta lift" href="/">Open JARVIS</a>
</main></div>
</body>
</html>
"""

router = APIRouter(include_in_schema=False)


def _settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def _mobile_on(request: Request) -> Settings:
    s = _settings(request)
    if not s.mobile_enabled:
        raise HTTPException(404, "not found")
    return s


@lru_cache(maxsize=1)
def _manifest_file() -> Mapping[str, Any]:
    data: dict[str, Any] = json.loads((_STATIC / "manifest.webmanifest").read_text("utf-8"))
    return data


def manifest(s: Settings) -> dict[str, Any]:
    """The manifest as it is served: the static file, without its share target when sharing
    is switched off."""
    m = dict(_manifest_file())
    if not s.app_share_enabled:
        m.pop("share_target", None)
    return m


@router.get(MANIFEST_PATH)
async def web_manifest(s: Settings = Depends(_mobile_on)) -> Response:
    body = json.dumps(manifest(s), ensure_ascii=False, indent=2).encode("utf-8")
    return Response(
        body,
        media_type=MANIFEST_TYPE,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/static/icons/{name}")
async def icon(name: str, _: Settings = Depends(_mobile_on)) -> FileResponse:
    if name not in ICONS:  # the literal allow-list: no path is ever built from the request
        raise HTTPException(404, "not found")
    return FileResponse(
        _STATIC / "icons" / name,
        media_type="image/png",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get(SHARE_SW_PATH)
async def share_worker(s: Settings = Depends(_mobile_on)) -> FileResponse:
    if not s.app_share_enabled:
        raise HTTPException(404, "not found")
    return FileResponse(
        _STATIC / "app-share-sw.js",
        media_type=_JS,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": CONSOLE_CSP,
            "Service-Worker-Allowed": SHARE_SCOPE,
        },
    )


@router.post(SHARE_IN_PATH)
async def share_missed(s: Settings = Depends(_mobile_on)) -> HTMLResponse:
    """The share worker takes this POST in the browser; when it was not installed yet the share
    reaches the server, which never reads it (no `request` here at all) and says what to do."""
    words = MISSED if s.app_share_enabled else SHARE_OFF
    return HTMLResponse(_PAGE.format(words=words), headers=_PAGE_HEADERS)


@router.get(SHARE_IN_PATH)
async def share_reloaded() -> RedirectResponse:
    return RedirectResponse("/", status_code=303)


@router.get("/app/status", dependencies=[Depends(require_auth)])
async def status(request: Request) -> JSONResponse:
    part = part_of(request, PART)
    s = _settings(request)
    body = {
        "part": PART,
        "ready": part.ready if part is not None else NOT_BUILT,
        "share": bool(s.mobile_enabled and s.app_share_enabled),
    }
    return JSONResponse(body, headers=NO_STORE)


class ShareTrayPrivacy:
    """D25: what only this browser holds. The share tray keeps shared items in the phone's own
    browser until a press; the server never holds them before that, so there is no count and
    nothing to delete from here (Discard is in the tray)."""

    id = "share_tray"
    section = "Phone app"
    label = "Shared items waiting on your phone"

    async def describe(self, uid: str) -> CategoryView:
        return CategoryView(
            id=self.id,
            section=self.section,
            label=self.label,
            what=(
                "Photos, PDFs and text you share into JARVIS from other apps wait in your "
                "phone's browser until you choose what to do with each. JARVIS never receives "
                "them before you press a button."
            ),
            count=None,
            unit="",
            retention="24 hours",
            where="Your phone's browser only",
            delete="none",
            note="Discard them in the share tray on your phone.",
        )

    async def export(self, uid: str) -> dict[str, Any] | None:
        return None

    async def delete(self, uid: str) -> int:
        return 0


def build(ctx: MobileContext) -> MobilePart:
    return MobilePart(
        PART,
        privacy=(ShareTrayPrivacy(),),
        ready=READY if ctx.s.mobile_enabled else OFF,
    )


__all__ = [
    "ICONS",
    "MANIFEST_PATH",
    "MISSED",
    "PART",
    "SHARE_EXTENSIONS",
    "SHARE_IN_PATH",
    "SHARE_OFF",
    "SHARE_SCOPE",
    "SHARE_SW_PATH",
    "ShareTrayPrivacy",
    "build",
    "manifest",
    "router",
]
