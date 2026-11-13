# tests/test_r7_a_static.py -- R7 Part A's console files, read as source (docs/plans/r7-mobile.md
# D0, D8, D12, D15; BRIEF-COMMON.md section 5): ASCII, textContent only, within their budgets; the
# stylesheet only places things; the launch reader never starts the microphone, never unlocks it
# and never asks the server anything; the share worker sends nothing anywhere and controls no page;
# the tray sends only through I0's one picture door and registers its worker only after sign-in.
# The browser tests (tests/browser/test_r7_a_*.py) prove the same things by behaviour.
from __future__ import annotations

import re

import pytest
from r7_fakes_a import STATIC, text

LINKS = STATIC / "console-r7-links.js"
SHARE = STATIC / "console-r7-share.js"
SHARE_CSS = STATIC / "console-r7-share.css"
SHARE_SW = STATIC / "app-share-sw.js"
PUSH_SW = STATIC / "console-sw.js"
OURS = (LINKS, SHARE, SHARE_CSS, SHARE_SW, PUSH_SW)


def _code(path_text: str) -> str:
    """The source without its comments (the headers name what the code must never do)."""
    no_block = re.sub(r"/\*.*?\*/", "", path_text, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$|\s//\s.*$", "", no_block)


@pytest.mark.parametrize("path", OURS, ids=lambda p: p.name)
def test_ascii_source_text_content_only_and_within_budget(path: object) -> None:
    src = text(path)  # type: ignore[arg-type]
    assert src.isascii()
    assert "innerHTML" not in src and "insertAdjacentHTML" not in src and "outerHTML" not in src
    assert "eval(" not in src and "new Function" not in src
    assert len(src.splitlines()) <= 800


def test_the_stylesheet_only_places_things() -> None:
    css = text(SHARE_CSS)
    assert len(css.splitlines()) <= 150
    rules = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for banned in (
        "color",
        "background",
        "font",
        "border",
        "radius",
        "shadow",
        "opacity",
        "#",
        "rgb",
        "var(--",
        "animation",
        "transition",
        "filter",
    ):
        assert banned not in rules, banned
    assert all(sel.strip().startswith((".r7s", ".sheet.r7s", "@media", "}")) for sel in
               re.findall(r"(?m)^([^{}\n]+)\{", rules))  # fmt: skip


# ---- the launch reader (D8) ---------------------------------------------------------------------
def test_the_launch_reader_never_starts_or_unlocks_the_microphone() -> None:
    code = _code(text(LINKS))
    for banned in (
        "press(",
        ".click(",
        "dispatchEvent(",
        "unlock(",
        "getUserMedia",
        "JarvisAudio",
        "SpeechRecognition",
        ".start(",
        "listen(",
        "MouseEvent",
        "PointerEvent",
        "KeyboardEvent",
    ):
        assert banned not in code, banned
    talk = code[code.index("function talk()") : code.index("async function partCall")]  # I1
    assert "mic.focus()" in talk and "loop.say(TALK_LINE)" in talk
    assert "const TALK_LINE = 'Tap to talk';" in code


def test_the_launch_reader_asks_the_server_nothing_and_cleans_the_address() -> None:
    code = _code(text(LINKS))
    for banned in ("fetch(", "M.api(", ".api(", "XMLHttpRequest", "sendBeacon", "WebSocket"):
        assert banned not in code, banned
    assert "history.replaceState(" in code and "const KEYS = ['do', 'open'];" in code
    assert "new BroadcastChannel('jarvis-launch')" in code
    assert "sessionStorage" in code and "localStorage" not in code  # this tab only


# ---- the share worker (D15) ---------------------------------------------------------------------
def test_the_share_worker_sends_nothing_anywhere_and_takes_one_post() -> None:
    code = _code(text(SHARE_SW))
    for banned in ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "importScripts"):
        assert banned not in code, banned
    assert "postMessage" not in code and "clients.claim" not in code  # it controls no page
    assert code.count("addEventListener('fetch'") == 1
    assert "req.method !== 'POST'" in code and "url.pathname !== '/app/share/in'" in code
    assert "Response.redirect(" in code and ", 303)" in code
    assert "const MAX_ITEMS = 5;" in code and "const MAX_BYTES = 10 * 1024 * 1024;" in code
    assert "const KEEP_MS = 24 * 60 * 60 * 1000;" in code
    assert re.search(r"const LANDING = '/\?do=shared';", code)


# ---- the tray (D12, D15) ------------------------------------------------------------------------
def test_the_tray_sends_only_through_the_one_picture_door() -> None:
    code = _code(text(SHARE))
    for banned in (
        "fetch(",
        "/v1/attachments",
        "/v1/vault",
        "/v1/chat",
        "JarvisAttach",
        "JarvisChat",
        "jarvis_r7_sent_v1",
        "XMLHttpRequest",
        "sendBeacon",
    ):
        assert banned not in code, banned
    assert "M.parts.send" in code
    for call in ("d.ask(file, ASK_TEXT)", "d.vault(file)", "d.attach([file])", "d.canAsk()"):
        assert call in code, call
    assert "d.line()" in code  # the one "Pictures sent from this device today" line


def test_the_tray_asks_the_server_only_after_sign_in() -> None:
    code = _code(text(SHARE))
    assert code.count("M.api(") == 1 and code.count("serviceWorker.register(") == 1
    worker = code[code.index("async function worker()") : code.index("async function ready()")]
    assert (
        "M.api('/app/status')" in worker
        and "register('/app/share/sw.js', { scope: SCOPE })" in worker
    )
    ready = code[code.index("async function ready()") :]
    assert "worker();" in ready
    assert (
        "document.addEventListener('jarvis:ready'" in ready and "if (signedIn()) ready();" in ready
    )
    opener = code[code.index("function open()") : code.index("async function show()")]
    assert "if (!signedIn()) { wanted = true;" in opener
