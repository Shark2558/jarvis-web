# tests/test_console_assets.py — self-hosted console assets: fonts and three.js (allow-listed,
# immutable), the console's own scripts/styles (no-store), the CSP, and packaging coverage.
from __future__ import annotations

import fnmatch
import re
import tomllib
from pathlib import Path

import pytest
from httpx import AsyncClient

from jarvis.api.console import APP_ASSETS, FONT_FILES, THREE_RELEASE, VENDOR_FILES

ROOT = Path(__file__).resolve().parents[1]
IMMUTABLE = "public, max-age=31536000, immutable"
# The console CSP is a security contract: any change here must be deliberate.
EXPECTED_CSP = (
    "default-src 'none'; script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; "
    "font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)

ALLOWED_FONTS = (
    "orbitron-latin-600-normal.woff2",
    "orbitron-latin-700-normal.woff2",
    "rajdhani-latin-500-normal.woff2",
    "rajdhani-latin-600-normal.woff2",
    "rajdhani-latin-700-normal.woff2",
    "share-tech-mono-latin-400-normal.woff2",
)
THREE_URL = f"/static/vendor/{THREE_RELEASE}/three.module.min.js"
DECK_SCRIPTS = (
    "console-fx.js",
    "console-deck.js",
    "console.js",
    "console-brief.js",
    "console-usage.js",
    "console-memory.js",
    "console-voice-capture.js",
    "console-voice-speech.js",
    "console-voice.js",
    "console-voice-mic.js",
)
MODULE_SCRIPTS = ("console-3d.js",)
MODULE_DEPS = (
    "console-3d-scenes.js",  # imported by console-3d.js, not by the page
    "voice-capture-worklet.js",  # loaded by audioWorklet.addModule (slice 9), not by the page
)
STYLES = ("console.css", "console-deck.css", "console-memory.css", "console-voice.css")
VOICE_SCRIPTS = (
    "console-voice-capture.js",
    "console-voice-speech.js",
    "console-voice.js",
    "console-voice-mic.js",
    "voice-capture-worklet.js",
)


# ---- fonts ------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ALLOWED_FONTS)
async def test_serves_each_allow_listed_font_as_woff2_with_long_cache(
    client: AsyncClient, name: str
) -> None:
    r = await client.get(f"/static/fonts/{name}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "font/woff2"
    assert r.headers["cache-control"] == IMMUTABLE
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.content[:4] == b"wOF2"  # real woff2 payload, not an HTML error page


def test_font_allow_list_is_exactly_the_shipped_fonts() -> None:
    assert set(ALLOWED_FONTS) == FONT_FILES


@pytest.mark.parametrize(
    "path",
    [
        "/static/fonts/evil.woff2",  # unknown name
        "/static/fonts/orbitron-latin-400-normal.woff2",  # real family, not shipped
        "/static/fonts/OFL-orbitron.txt",  # exists on disk but is not a served font
        "/static/fonts/OFL-share-tech-mono.txt",
        "/static/fonts/ORBITRON-LATIN-700-NORMAL.WOFF2",  # no case folding
        "/static/fonts/console.html",
        "/static/fonts/..%2Fconsole.html",  # encoded traversal
        "/static/fonts/%2e%2e%2f%2e%2e%2fconsole.py",
        "/static/fonts/..%5Cconsole.py",  # backslash traversal
        "/static/fonts/",
    ],
)
async def test_rejects_unknown_font_names_and_traversal(client: AsyncClient, path: str) -> None:
    r = await client.get(path)
    assert r.status_code == 404
    assert r.content[:4] != b"wOF2"
    assert b"<html" not in r.content.lower()


async def test_console_page_declares_self_hosted_font_faces(client: AsyncClient) -> None:
    html = (await client.get("/")).text
    for name in ALLOWED_FONTS:
        assert f"/static/fonts/{name}" in html
    assert "font-display:swap" in html.replace(" ", "")


# ---- three.js (vendored, MIT) -----------------------------------------------------------------
async def test_serves_vendored_three_as_javascript_with_immutable_cache(
    client: AsyncClient,
) -> None:
    r = await client.get(THREE_URL)
    assert r.status_code == 200
    assert re.match(r"(application|text)/javascript", r.headers["content-type"])
    assert r.headers["cache-control"] == IMMUTABLE
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.text.startswith("/* three.js r187")
    assert 'var Al="187"' in r.text or '"187"' in r.text  # the real REVISION constant


def test_three_licence_ships_beside_the_vendored_build() -> None:
    lic = ROOT / "src/jarvis/api/static/vendor/LICENSE-three.txt"
    assert lic.is_file() and "MIT License" in lic.read_text(encoding="utf-8")
    assert THREE_RELEASE == "three-0.187.0"


@pytest.mark.parametrize(
    "path",
    [
        f"/static/vendor/{THREE_RELEASE}/three.core.min.js",  # not shipped
        f"/static/vendor/{THREE_RELEASE}/three.module.js",
        f"/static/vendor/{THREE_RELEASE}/LICENSE-three.txt",  # on disk, not served
        f"/static/vendor/{THREE_RELEASE}/THREE.MODULE.MIN.JS",  # no case folding
        "/static/vendor/three-0.186.0/three.module.min.js",  # wrong release
        "/static/vendor/three.module.min.js",  # missing release segment
        f"/static/vendor/{THREE_RELEASE}/",
        f"/static/vendor/{THREE_RELEASE}/..%2F..%2Fconsole.py",
        f"/static/vendor/{THREE_RELEASE}/%2e%2e%2fconsole.html",
        "/static/vendor/..%2Fconsole.html/three.module.min.js",
    ],
)
async def test_rejects_unknown_vendor_names_releases_and_traversal(
    client: AsyncClient, path: str
) -> None:
    r = await client.get(path)
    assert r.status_code == 404
    assert b"three.js" not in r.content


# ---- the console's own scripts and styles -----------------------------------------------------
@pytest.mark.parametrize("name", DECK_SCRIPTS + MODULE_SCRIPTS + MODULE_DEPS + STYLES)
async def test_serves_console_assets_with_right_type_and_no_store(
    client: AsyncClient, name: str
) -> None:
    r = await client.get(f"/static/{name}")
    assert r.status_code == 200
    kind = "css" if name.endswith(".css") else "javascript"
    assert kind in r.headers["content-type"]
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    "path",
    [
        "/static/evil.js",
        "/static/console.html",
        "/static/console.py",
        "/static/CONSOLE.JS",
        "/static/..%2Fconsole.py",
        "/static/vendor",
        "/static/fonts",
    ],
)
async def test_rejects_unknown_console_assets(client: AsyncClient, path: str) -> None:
    r = await client.get(path)
    assert r.status_code == 404


async def test_console_page_keeps_exact_csp_and_loads_deck_and_3d_modules(
    client: AsyncClient,
) -> None:
    r = await client.get("/")
    assert r.headers["content-security-policy"] == EXPECTED_CSP
    html = r.text
    for name in DECK_SCRIPTS:
        assert f'<script src="/static/{name}" defer></script>' in html
    for name in MODULE_SCRIPTS:
        assert f'<script type="module" src="/static/{name}"></script>' in html
    for name in STYLES:
        assert f'<link rel="stylesheet" href="/static/{name}">' in html
    # no inline script (CSP forbids it anyway) and no third-party hosts
    for tag in re.findall(r"<script\b[^>]*>", html):
        assert 'src="/static/' in tag
    assert "https://" not in html and "http://" not in html


async def test_3d_module_imports_three_only_from_the_allow_listed_vendor_url(
    client: AsyncClient,
) -> None:
    js = (await client.get("/static/console-3d.js")).text
    specifiers = set(re.findall(r"import\(\s*['\"]([^'\"]+)['\"]", js))
    specifiers |= set(re.findall(r"\bfrom\s*['\"]([^'\"]+)['\"]", js))
    vendor = {s for s in specifiers if "/vendor/" in s}
    assert vendor == {THREE_URL}
    assert all(s.startswith(("/static/", "./")) for s in specifiers)
    assert "eval(" not in js and "new Function" not in js


def test_every_served_asset_is_covered_by_package_data() -> None:
    """The image installs with `pip install .`, so a file missing from package-data 404s in prod."""
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    globs = cfg["tool"]["setuptools"]["package-data"]["jarvis.api"]
    served = (
        ["static/console.html"]
        + [f"static/{n}" for n in APP_ASSETS]
        + [f"static/fonts/{n}" for n in FONT_FILES]
        + [f"static/vendor/{n}" for n in VENDOR_FILES]
        + ["static/vendor/LICENSE-three.txt", "static/fonts/OFL-share-tech-mono.txt"]
    )
    base = ROOT / "src/jarvis/api"
    for rel in served:
        assert (base / rel).is_file(), rel
        assert any(fnmatch.fnmatch(rel, g) for g in globs), f"{rel} not in package-data"


# ---- slice 7: the Brief panel -------------------------------------------------------------------
async def test_brief_script_finds_the_console_ready_however_late_it_arrives(
    client: AsyncClient,
) -> None:
    """Review M1: jarvis:ready fires once. console-brief.js (deferred, after console.js) can arrive
    after it on a slow network, so it also asks window.JarvisConsole.ready() when it starts."""
    html = (await client.get("/")).text
    # console-brief.js reads window.JarvisDeck when it starts; JarvisConsole only when it calls
    names = ("console-deck.js", "console.js", "console-brief.js")
    order = [html.index(f'src="/static/{n}"') for n in names]
    assert order == sorted(order)
    console_js = (await client.get("/static/console.js")).text
    frozen = "window.JarvisConsole = Object.freeze({ api, ready: () => readyDetail, "
    assert frozen + "brain: () => brainDetail })" in console_js
    assert "readyDetail = Object.freeze({ returning: backFromGoogle })" in console_js
    assert console_js.index("readyDetail = Object.freeze(") < console_js.index(
        "emit('jarvis:ready', readyDetail)"
    )
    brief_js = (await client.get("/static/console-brief.js")).text
    assert "document.addEventListener('jarvis:ready'" in brief_js
    assert re.search(r"typeof \w+\.ready === 'function' \? \w+\.ready\(\) : null", brief_js)


HTML_SINKS = (
    "innerHTML",
    "outerHTML",
    "insertAdjacentHTML",
    "document.write",
    "writeln",
    "createContextualFragment",
    "DOMParser",
    "setHTMLUnsafe",
    "parseHTMLUnsafe",
    "srcdoc",
    ".href =",
    "eval(",
    "new Function",
)
# the same, however it is spaced or quoted: URL and handler attributes, string timers
_URLISH = r"(?:on|href|src|srcdoc|action|formaction|xlink:href)"
SINK_PATTERNS = (
    r"\.(?:href|src|action|formAction)\s*=(?!=)",
    rf"setAttribute\(\s*['\"`]{_URLISH}",
    rf"setAttributeNS\([^,]*,\s*['\"`]{_URLISH}",
    r"set(?:Timeout|Interval)\(\s*['\"`]",
)


def _sinks(js: str) -> list[str]:
    """Every sink named in `js`. The whole text is scanned, comments included: stripping "//..."
    would also hide code that follows a "//" inside a string ('https://x'; el.innerHTML = s)."""
    found = [s for s in HTML_SINKS if s in js]
    return found + [p for p in SINK_PATTERNS if re.search(p, js)]


@pytest.mark.parametrize(
    "js",
    [
        "const u = 'https://x.example/'; el.innerHTML = s;",
        "el.insertAdjacentHTML('beforeend', s)",
        "document.writeln(s)",
        "document.createRange().createContextualFragment(s)",
        "new DOMParser().parseFromString(s, 'text/html')",
        "el.setHTMLUnsafe(s)",
        "frame.srcdoc = s",
        "a.href = s",
        "a.href=s",
        "img.src = s",
        "el.setAttribute('onclick', s)",
        'el.setAttribute( "href", s)',
        "el.setAttributeNS(null, 'onload', s)",
        "setTimeout('run()', 10)",
    ],
)
def test_the_sink_scan_finds_each_sink(js: str) -> None:
    assert _sinks(js), js


def test_the_sink_scan_passes_safe_dom_code() -> None:
    safe = "el.textContent = s; el.setAttribute('aria-label', s); l.htmlFor = 'x'; a === b;"
    assert _sinks(safe) == []


async def test_brief_script_never_parses_server_text_as_html(client: AsyncClient) -> None:
    js = (await client.get("/static/console-brief.js")).text
    assert _sinks(js) == []
    assert "textContent" in js
    # every write goes through the console's api() (cookie + X-Requested-With, or bearer token)
    assert "fetch(" not in js
    assert "/v1/brief/today" in js and "/v1/brief/generate" in js and "/v1/brief/seen" in js
    assert "confirm_spend: true" in js and "confirm_inbox: true" in js


async def test_brief_panel_and_dock_button_are_wired(client: AsyncClient) -> None:
    html = (await client.get("/")).text
    assert 'id="p-brief" data-panel="brief" aria-labelledby="t-brief"' in html
    assert 'data-open="brief" aria-controls="p-brief" aria-pressed="false"' in html
    assert '<dialog class="bdialog" id="briefDialog" role="alertdialog"' in html
    assert 'id="briefNote" role="status"' in html
    deck = (await client.get("/static/console-deck.js")).text
    assert "'chat', 'brief', 'approvals'" in deck  # in the deck's order and default layout
    assert re.search(r"\bbrief: \{ x:", deck)


async def test_privacy_banner_sits_in_the_deck_flow_not_over_panels(client: AsyncClient) -> None:
    """Review HIGH 1: a fixed banner covered panel title bars; it must be an in-flow grid strip."""
    css = (await client.get("/static/console-deck.css")).text
    rules = re.findall(r"([^{}]+)\{([^{}]*)\}", css)
    notice = [body for sel, body in rules if ".deck > .notice" in sel]
    assert notice, "the deck must style its privacy banner"
    assert all("position:fixed" not in body.replace(" ", "") for body in notice)
    assert any("grid-area:notice" in body.replace(" ", "") for body in notice)


# ---- slice 7b: costs in rupees, this month's spend and the limit ---------------------------------
async def test_usage_script_never_parses_server_text_as_html(client: AsyncClient) -> None:
    js = (await client.get("/static/console-usage.js")).text
    assert _sinks(js) == []
    assert "textContent" in js and "fetch(" not in js  # the console's api() only
    assert "/v1/usage" in js and "/v1/usage/budget" in js
    # raising and removing send the confirmation; the plain body (a lower) does not
    assert "{ monthly_limit_inr: want, confirm_raise: true }" in js
    assert "{ monthly_limit_inr: null, confirm_raise: true }" in js
    assert "{ monthly_limit_inr: want }" in js


async def test_usage_script_loads_after_the_console_and_finds_it_ready(client: AsyncClient) -> None:
    html = (await client.get("/")).text
    names = ("console-deck.js", "console.js", "console-usage.js")
    order = [html.index(f'src="/static/{n}"') for n in names]
    assert order == sorted(order)
    js = (await client.get("/static/console-usage.js")).text
    assert "document.addEventListener('jarvis:ready'" in js
    assert re.search(r"typeof \w+\.ready === 'function' && \w+\.ready\(\)", js)


def _visible_strings(js: str) -> list[str]:
    """String and template literals in `js` (what can reach the page as text)."""
    return re.findall(r"'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`|\"(?:[^\"\\\n]|\\.)*\"", js)


@pytest.mark.parametrize(
    "name",
    [
        "console.js",
        "console-deck.js",
        "console-usage.js",
        "console-brief.js",
        "console-memory.js",
        *VOICE_SCRIPTS,
    ],
)
def test_no_dollar_sign_in_any_console_string(name: str) -> None:
    """Every cost the owner sees is in rupees. A template's ${…} is code, not text."""
    js = (ROOT / "src/jarvis/api/static" / name).read_text(encoding="utf-8")
    for lit in _visible_strings(js):
        assert "$" not in re.sub(r"\$\{", "", lit), (name, lit[:80])


async def test_console_page_text_has_rupees_and_no_dollars(client: AsyncClient) -> None:
    html = (await client.get("/")).text
    text = re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S))
    assert "$" not in text
    assert 'id="sCost">₹0.00<' in html
    assert ">Last reply by<" in html and ">Model<" not in html  # rail and Vitals both renamed
    assert 'id="spend"' in html and 'id="limitBtn"' in html
    assert '<dialog class="bdialog" id="limitDialog" role="alertdialog"' in html


# ---- slice 8: long-term memory, collapsed settings, the phone "More" sheet ----------------------
# The one URL the Memory panel ever assigns: the blob: URL of the export it has just built in the
# page (never server text), so the browser saves it as a file.
EXPORT_LINK = "a.href = URL.createObjectURL(blob)"


async def test_memory_script_never_parses_memory_text_as_html(client: AsyncClient) -> None:
    js = (await client.get("/static/console-memory.js")).text
    assert js.count(EXPORT_LINK) == 1
    assert _sinks(js.replace(EXPORT_LINK, "")) == []
    assert "textContent" in js and "fetch(" not in js  # the console's api() only
    for path in (
        "'/v1/memory'",
        "'/v1/memory/settings'",
        "'/v1/memory/profile/'",
        "'/v1/memory/facts'",
        "'/v1/memory/facts/'",
        "'/v1/memory/export'",
        "'/v1/memory/import'",
    ):
        assert path in js, path
    # learning spends money: it is switched on only with the confirmation flag
    assert "{ learn: true, confirm_spend: true }" in js
    assert "{ confirm: 'FORGET' }" in js
    assert "encodeURIComponent(" in js  # fact ids never shape the path by themselves


async def test_memory_script_loads_after_the_console_and_finds_it_ready(
    client: AsyncClient,
) -> None:
    html = (await client.get("/")).text
    names = ("console-deck.js", "console.js", "console-memory.js")
    order = [html.index(f'src="/static/{n}"') for n in names]
    assert order == sorted(order)
    js = (await client.get("/static/console-memory.js")).text
    assert "document.addEventListener('jarvis:ready'" in js
    assert re.search(r"typeof \w+\.ready === 'function' \? \w+\.ready\(\) : null", js)


async def test_memory_panel_dock_button_and_dialog_are_wired(client: AsyncClient) -> None:
    html = (await client.get("/")).text
    assert 'id="p-memory" data-panel="memory" aria-labelledby="t-memory"' in html
    assert 'data-open="memory" aria-controls="p-memory" aria-pressed="false"' in html
    assert '<dialog class="bdialog" id="memoryDialog" role="alertdialog"' in html
    assert 'id="memoryNote" role="status"' in html
    # every field has a visible label; the settings start collapsed
    for label in ("about", "preferences", "people", "work"):
        assert f'<label class="bl" for="memP-{label}">' in html, label
        assert f'id="memP-{label}" maxlength="1000"' in html, label
    assert 'id="memSetBtn" type="button" aria-expanded="false" aria-controls="memSetBody"' in html
    assert 'id="memSetBody" hidden' in html
    assert 'id="memForgetIn"' in html and 'id="memAddText" maxlength="300"' in html
    deck = (await client.get("/static/console-deck.js")).text
    assert "'history', 'memory', 'integrations'" in deck  # in the deck's order and default layout
    assert re.search(r"\bmemory: \{ x:", deck)


async def test_phone_dock_has_a_more_sheet_for_the_overflow_tabs(client: AsyncClient) -> None:
    """Ten panels (Voice joined in slice 9): a phone shows at most eight tabs; the rest sit behind
    "More"."""
    html = (await client.get("/")).text
    dock = html[html.index('<nav class="dock card"') : html.index("</nav>")]
    tabs = re.findall(r'<button class="dk([^"]*)" type="button" data-open="(\w+)"', dock)
    assert len(tabs) == 10
    on_phone = [name for cls, name in tabs if "ovf" not in cls.split()]
    overflow = [name for cls, name in tabs if "ovf" in cls.split()]
    assert len(on_phone) + 1 <= 8 and overflow  # + the More tab itself
    assert 'id="dockMore" type="button" aria-haspopup="dialog" aria-expanded="false"' in dock
    assert '<dialog class="sheet" id="moreSheet" aria-labelledby="moreTitle">' in html
    for name in overflow:
        assert f'data-sheet-open="{name}"' in html, name
    css = (await client.get("/static/console-deck.css")).text
    assert re.search(r"\.dk\.ovf\s*\{[^}]*display:\s*none", css)  # inside the phone query


async def test_brief_settings_sit_behind_a_remembered_disclosure(client: AsyncClient) -> None:
    js = (await client.get("/static/console-brief.js")).text
    assert "'aria-expanded'" in js and "'aria-controls'" in js
    assert "jarvis_brief_settings_open" in js
    # storage may throw (private mode, blocked site data): every access is wrapped
    assert re.search(r"try \{ return localStorage\.getItem\(k\); \} catch", js)
    assert re.search(r"try \{ localStorage\.setItem\(k, v\); \} catch", js)


async def test_reply_meta_lists_the_memories_used_as_text(client: AsyncClient) -> None:
    js = (await client.get("/static/console.js")).text
    assert "memory_used" in js and "Used " in js
    assert "emit('jarvis:brain'" in js


# ---- slice 9: voice -------------------------------------------------------------------------------
@pytest.mark.parametrize("name", VOICE_SCRIPTS)
async def test_voice_scripts_never_parse_text_as_html_and_use_the_console_transport(
    client: AsyncClient, name: str
) -> None:
    js = (await client.get(f"/static/{name}")).text
    assert _sinks(js) == [], name
    # bytes and JSON both go through console.js (cookie + X-Requested-With, or the bearer token)
    assert "fetch(" not in js and "XMLHttpRequest" not in js and "WebSocket" not in js, name
    assert "https://" not in js and "http://" not in js, name


async def test_voice_scripts_load_after_the_console_in_order(client: AsyncClient) -> None:
    html = (await client.get("/")).text
    names = (
        "console-deck.js",
        "console.js",
        "console-voice-capture.js",
        "console-voice-speech.js",
        "console-voice.js",
        "console-voice-mic.js",
    )
    order = [html.index(f'src="/static/{n}"') for n in names]
    assert order == sorted(order)
    voice = (await client.get("/static/console-voice.js")).text
    assert "document.addEventListener('jarvis:ready'" in voice
    assert re.search(r"typeof \w+\.ready === 'function' \? \w+\.ready\(\) : null", voice)
    mic = (await client.get("/static/console-voice-mic.js")).text
    assert "document.addEventListener('jarvis:ready'" in mic
    assert re.search(r"typeof \w+\.ready === 'function' && \w+\.ready\(\)", mic)


async def test_voice_contract_paths_headers_and_channel(client: AsyncClient) -> None:
    """§3 of docs/plans/phase1-slice9-voice.md, as the console uses it."""
    voice = (await client.get("/static/console-voice.js")).text
    for path in ("'/v1/voice'", "'/v1/voice/settings'", "'/v1/voice/speak'"):
        assert path in voice, path
    assert "{ preview: true, voice: meta.preview" in voice
    mic = (await client.get("/static/console-voice-mic.js")).text
    assert "'/v1/voice/transcribe'" in mic
    assert "'Content-Type': 'audio/wav'" in mic
    assert "Chat.send(text, { channel: 'voice' })" in mic
    # D11: the fixed, wit-free approval line, and nothing in the voice code ever approves
    assert "That one needs your approval on screen, ${honorific()}." in mic
    for name in VOICE_SCRIPTS:
        js = (await client.get(f"/static/{name}")).text
        assert "/approve" not in js and "/v1/approvals" not in js, name
    console_js = (await client.get("/static/console.js")).text
    assert "if (channel === 'voice') body.channel = 'voice';" in console_js
    assert "headers = Object.assign({}, opts.headers || {}, { 'X-Requested-With': 'JARVIS' })" in console_js
    assert "window.JarvisChat = Object.freeze({" in console_js


async def test_capture_worklet_is_served_and_loaded_from_this_server_only(
    client: AsyncClient,
) -> None:
    capture = (await client.get("/static/console-voice-capture.js")).text
    assert "const WORKLET_URL = '/static/voice-capture-worklet.js';" in capture
    assert "addModule(WORKLET_URL)" in capture
    worklet = (await client.get("/static/voice-capture-worklet.js")).text
    assert "registerProcessor('jarvis-capture'" in worklet
    assert "const FRAME = 1280;" in worklet and "const OUT_RATE = 16000;" in worklet
    # the microphone is asked for with the browser's own clean-up switched on (D4)
    for flag in ("echoCancellation: true", "noiseSuppression: true", "autoGainControl: true"):
        assert flag in capture, flag


async def test_voice_panel_dock_tab_and_more_sheet_are_wired(client: AsyncClient) -> None:
    html = (await client.get("/")).text
    assert 'id="p-voice" data-panel="voice" aria-labelledby="t-voice"' in html
    assert 'data-open="voice" aria-controls="p-voice" aria-pressed="false"' in html
    assert 'data-sheet-open="voice"' in html
    assert 'id="voiceNote" role="status" aria-live="polite"' in html
    assert 'id="micBtn" type="button" aria-pressed="false"' in html
    assert 'aria-keyshortcuts="Control+Space"' in html
    assert 'id="voiceLive" role="status" aria-live="polite"' in html
    deck = (await client.get("/static/console-deck.js")).text
    assert "'integrations', 'voice', 'vitals'" in deck
    assert re.search(r"\bvoice: \{ x:", deck)
    # device settings: storage may throw (private mode, blocked site data)
    voice = (await client.get("/static/console-voice.js")).text
    assert re.search(r"try \{ return localStorage\.getItem\(k\); \} catch", voice)
    assert re.search(r"try \{ localStorage\.setItem\(k, v\); \} catch", voice)
    assert "wake: false" in voice  # "Hey Jarvis" is off by default on every device
    assert "openWakeWord (CC BY-NC-SA 4.0), personal use" in voice
