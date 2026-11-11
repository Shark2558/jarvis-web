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
    "console-dock.js": _JS,  # R6.1 D7: the dock fits every screen (folds tabs behind More)
    "console-brief.js": _JS,  # morning Brief panel: today's brief, its settings and confirms
    "console-usage.js": _JS,  # Vitals: this month's AI spend in rupees and the owner's limit
    "console-memory.js": _JS,  # Memory panel: About you, facts, learning consent (slice 8)
    "console-voice-capture.js": _JS,  # slice 9: microphone → 16 kHz frames, energy VAD, WAV
    "console-voice-speech.js": _JS,  # slice 9: reply → speakable chunks, Web Audio playback queue
    "console-voice.js": _JS,  # slice 9: Voice panel, voice settings, engines
    "console-voice-mic.js": _JS,  # slice 9: composer mic, spoken turns, "Hey Jarvis" wiring
    "console-voice-commands.js": _JS,  # R5 D12: the local voice-command router (core)
    "console-voice-devices-match.js": _JS,  # R5 D13: device matching and kind words (pure)
    "console-voice-devices.js": _JS,  # R5 D13: audio route (output / input devices)
    "console-voice-devices-panel.js": _JS,  # R5 D13: Voice -> Sound devices
    "console-voice-pace.js": _JS,  # R5 D15: sound cues and the timing line
    "console-voice-phrases.js": _JS,  # R5 D16: Voice -> Words to recognise
    "console-voice-barge.js": _JS,  # R5 D7: speak-to-interrupt gate and policy
    "console-voice-conversation.js": _JS,  # R5 D4: follow-up, standby, long pause, check-in
    "console-voice-wake.js": _JS,  # R5: "Hey Jarvis" controller, moved out of the mic script
    "console-voice-micoff.js": _JS,  # R5 D11: the mic-off button, shortcut and announcements
    "console-voice-loop-glue.js": _JS,  # R5: barge, check-in and handover glue (from mic.js)
    "console-voice-loop-browser.js": _JS,  # R5: the browser engine's turn (from mic.js)
    "voice-capture-worklet.js": _JS,  # slice 9: AudioWorkletProcessor (downsample to 16 kHz)
    "console-3d.js": _JS,  # three.js scenes (ES module; loads three lazily, 2D fallback)
    "console-3d-scenes.js": _JS,  # Core / Globe / Construct scene builders (ES module)
    "console-wakeword.js": _JS,  # on-device "Hey Jarvis" (openWakeWord port, slice 9 D12)
    "console-web.js": _JS,  # slice 10 B: the Sources row under replies, Vitals web-search line
    "console-permissions.js": _JS,  # slice 10 D: Allow / Ask first / Never, passkeys (WebAuthn)
    "console-attach.js": _JS,  # slice 10 E: paperclip, drag-and-drop, file chips
    "console-approve-all.js": _JS,  # slice 11 D6: "Approve all (n)" above the Approvals list
    "console-approvals.js": _JS,  # slice 11 review: a card's Approve / Decline, Approve all's path
    "console-attach.css": "text/css",
    "console-deleted.js": _JS,  # slice 11: Approvals → Recently deleted, the reply's Undo chip
    "console-deleted.css": "text/css",
    "console-drive.js": _JS,  # slice 12 D1: Integrations → Google Drive (address, folders, Use)
    "console-drive.css": "text/css",
    "console-media.js": _JS,  # slice 12: Maps / YouTube cards, Media panel, Vitals, Home / Work
    "console-media.css": "text/css",
    "console-text.js": _JS,  # slice 12 final review: one invisible-character rule (keeps ZWJ)
    "console-whatsapp.js": _JS,  # slice 12 D6: the WhatsApp draft card (Open in WhatsApp)
    "console-whatsapp.css": "text/css",
    "console-integrations.js": _JS,  # slice 12 review C5: Integrations, out of console.js
    "console-telegram.js": _JS,  # R1 A: Integrations -> Telegram (pair, privacy, alerts)
    "console-telegram.css": "text/css",
    "console-activity.js": _JS,  # R1 B: Activity (what JARVIS did, with Undo)
    "console-activity.css": "text/css",
    "console-offline.js": _JS,  # R1 C: Integrations -> Offline mode, reply marker, Vitals line
    "console-offline.css": "text/css",
    "console-family.js": _JS,  # R1 D: Integrations -> Family calendars
    "console-family.css": "text/css",
    "console-brief-sections.js": _JS,  # R1 D + R2 A: Deliveries, Family today, Documents
    "console-vault.js": _JS,  # R2 A: the Vault panel (list, unlock, open, export)
    "console-vault-add.js": _JS,  # R2 A: Vault -> Add (upload, the proposal, Confirm)
    "console-vault.css": "text/css",
    "console-things.js": _JS,  # R2 B: Things ("Where did I keep it?")
    "console-things.css": "text/css",
    "console-notes.js": _JS,  # R2 C: Notes, memos and links
    "console-notes-memo.js": _JS,  # R2 C: Record a voice memo (transcript only)
    "console-notes.css": "text/css",
    "console-privacy.js": _JS,  # R2 D: the Privacy panel
    "console-privacy.css": "text/css",
    "console-home.js": _JS,  # R3 A: Integrations -> Home (link, kit, devices)
    "console-home.css": "text/css",
    "console-home-panel.js": _JS,  # R3 B: the Home panel (alarm, cameras, feed, history)
    "console-home-panel.css": "text/css",
    "console-faces.js": _JS,  # R3 C: the Faces panel (consent, delete with a passkey)
    "console-faces.css": "text/css",
    "console-alerts.js": _JS,  # R3 D: Integrations -> Alerts (quiet hours, VIPs, this device)
    "console-alerts.css": "text/css",
    "console-sw.js": _JS,  # R3 D: the service worker (push, notificationclick; /static/push/)
    "console-vitals.js": _JS,  # R4 A: Vitals -> the board (keys, quotas, bills, expiry; no key)
    "console-systems.js": _JS,  # R4 B: Integrations -> Systems check (Run, per-system rows, Speak)
    "console-connectors.js": _JS,  # R4 C: Connectors (GitHub token in the panel, YouTube, Photos)
    "console-people.js": _JS,  # R4 D: People research + the top-bar Brain pill (R5.1 D9)
    "console-systems-modal.js": _JS,  # R5.1 C: the systems-check pop-up (ticks, briefing, reminder)
    "console-systems-voice.js": _JS,  # R5.1 C: its phrases, speech and echo guard
    "console-vitals.css": "text/css",  # R5.1 B: the Vitals board (groups, chips, the add form)
    "console-systems.css": "text/css",  # R5.1 C: Systems card + pop-up
    "console-connectors.css": "text/css",  # R5.1 A: Connectors as Integrations-style cards
    "console-people.css": "text/css",  # R5.1 A: People panel + the top-bar Brain pill
    "console.css": "text/css",
    "console-deck.css": "text/css",
    "console-memory.css": "text/css",
    "console-voice.css": "text/css",
    "console-voice-devices.css": "text/css",
    "console-permissions.css": "text/css",
    # R6 (docs/plans/r6-build-book.md D15, D16; builder D): the Book panel in the deck, then the
    # show page (/book/show, book.html). The 3D files are ES modules; the scene modules are
    # imported by console-book-3d.js, never linked.
    "console-book.js": _JS,  # the Book panel (#p-book): status, open, sections, download
    "console-book-reader.js": _JS,  # the sections reader
    "console-book.css": "text/css",
    "console-book-show.js": _JS,  # the show: timeline, controls, captions
    "console-book-voice.js": _JS,  # narration: Web Audio queue, browser-voice fallback
    "console-book-3d.js": _JS,  # the 3D engine and governor (ES module)
    "console-book-scenes.js": _JS,  # scenes 1, 2, 12, 13 (ES module)
    "console-book-scenes-flow.js": _JS,  # scenes 3, 5, 6, 8 (ES module)
    "console-book-scenes-data.js": _JS,  # scenes 4, 7, 9-11 (ES module)
    "console-book-2d.js": _JS,  # the 2D show (phones, reduced motion, no WebGL2)
    "console-book-talk.js": _JS,  # questions, the closing, hand-back, Resume
    "book.css": "text/css",  # the show page
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

# Vendored onnxruntime-web (MIT; LICENSE-onnxruntime.txt, ThirdPartyNotices and MANIFEST.txt with
# the pinned sha256s beside it) for the on-device wake word: only the single-threaded WASM CPU
# build — the ES module, its Emscripten loader and the binary it instantiates.
ORT_RELEASE = "ort-1.30.0"
ORT_FILES: dict[str, str] = {
    "ort.wasm.min.mjs": _JS,
    "ort-wasm-simd-threaded.mjs": _JS,
    "ort-wasm-simd-threaded.wasm": "application/wasm",  # instantiateStreaming insists on it
}
_ORT = _VENDOR / "ort"

# openWakeWord v0.5.1 release models (CC BY-NC-SA 4.0: personal, non-commercial use only —
# wakeword/LICENSE.txt). Loaded by console-wakeword.js only when the owner switches it on.
WAKEWORD_RELEASE = "oww-0.5.1"
WAKEWORD_FILES = frozenset({"melspectrogram.onnx", "embedding_model.onnx", "hey_jarvis_v0.1.onnx"})
_WAKEWORD = _STATIC / "wakeword"

# The console CSP. 'wasm-unsafe-eval' lets the wake word compile onnxruntime's WebAssembly (and
# nothing else: it does not allow eval or new Function); no blob: or other host is needed.
# Slice 12 D4: the Media panel plays a video the owner chose in YouTube's privacy-enhanced embed —
# the one frame source allowed. No YouTube script runs in the console (no IFrame API), so
# script-src and connect-src stay 'self'.
# R3 D11: browser notifications need one service worker (console-sw.js, push and notificationclick
# only, no fetch handler) registered with scope /static/push/, so it controls no page. It would
# load under script-src 'self' anyway; `worker-src 'self'` says so explicitly (no blob: worker).
CONSOLE_CSP = (
    "default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; "
    "font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; "
    "frame-src https://www.youtube-nocookie.com; worker-src 'self'"
)
# The console page sends no referrer anywhere. Slice 12 D4: YouTube's player needs the embedding
# ORIGIN (error 153 without one), so only the player's own iframe carries
# referrerpolicy="strict-origin-when-cross-origin" (console-media.js) — never a path or query.


def _settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def _page(name: str) -> HTMLResponse:
    """A console page: never cached, never framed, no referrer, the ONE console CSP."""
    html = (_STATIC / name).read_text(encoding="utf-8")
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": CONSOLE_CSP,
        },
    )


@router.get("/", include_in_schema=False, response_class=HTMLResponse)
async def console() -> HTMLResponse:
    return _page("console.html")


@router.get("/book/show", include_in_schema=False, response_class=HTMLResponse)
async def book_show() -> HTMLResponse:
    """R6 D15/D16: the build book show (book.html), with the console's CSP unchanged. The page
    holds no data; it asks /v1/book/show/* with the book token. Under a guest lock (D10) it is
    where every console of the owner is sent."""
    return _page("book.html")


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


def _immutable(path: Path, media_type: str) -> FileResponse:
    """A versioned vendored file: its release is in the URL, so it may be cached for a year."""
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Cache-Control": _IMMUTABLE, "X-Content-Type-Options": "nosniff"},
    )


@router.get("/static/vendor/{release}/{name}", include_in_schema=False)
async def console_vendor(release: str, name: str) -> FileResponse:
    if release == THREE_RELEASE and name in VENDOR_FILES:
        return _immutable(_VENDOR / name, _JS)
    if release == ORT_RELEASE and name in ORT_FILES:
        return _immutable(_ORT / name, ORT_FILES[name])
    raise HTTPException(404, "not found")


@router.get("/static/wakeword/{release}/{name}", include_in_schema=False)
async def console_wakeword_model(release: str, name: str) -> FileResponse:
    if release != WAKEWORD_RELEASE or name not in WAKEWORD_FILES:
        raise HTTPException(404, "not found")
    return _immutable(_WAKEWORD / name, "application/octet-stream")


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
