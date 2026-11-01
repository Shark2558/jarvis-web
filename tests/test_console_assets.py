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
DECK_SCRIPTS = ("console-fx.js", "console-deck.js", "console.js", "console-brief.js")
MODULE_SCRIPTS = ("console-3d.js",)
MODULE_DEPS = ("console-3d-scenes.js",)  # imported by console-3d.js, not by the page
STYLES = ("console.css", "console-deck.css")


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
    assert "window.JarvisConsole = Object.freeze({ api, ready: () => readyDetail })" in console_js
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
