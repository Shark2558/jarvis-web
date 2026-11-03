# tests/test_drive_console.py — Integrations → Google Drive's static contract (slice 12 D1): served
# like the other console assets, loaded after the console, no HTML sinks, the console's transport
# only, textContent only, the plain-English steps, the "not offered" line, no dollar signs.
from __future__ import annotations

import re
from pathlib import Path

from httpx import AsyncClient
from test_console_assets import _sinks, _visible_strings  # same directory (pytest prepend import)

ROOT = Path(__file__).resolve().parents[1]


async def test_drive_script_and_style_are_served_no_store(client: AsyncClient) -> None:
    for name, kind in (("console-drive.js", "javascript"), ("console-drive.css", "css")):
        r = await client.get(f"/static/{name}")
        assert r.status_code == 200 and kind in r.headers["content-type"]
        assert r.headers["cache-control"] == "no-store"


async def test_drive_script_never_parses_server_text_as_html(client: AsyncClient) -> None:
    js = (await client.get("/static/console-drive.js")).text
    assert _sinks(js) == []
    assert "textContent" in js and "fetch(" not in js  # the console's api() only
    assert "'/v1/drive'" in js
    assert (
        "`/v1/drive/roots/${encodeURIComponent(f.id)}`, { method: 'PUT', body: { use: on } }" in js
    )
    assert "import " not in js and "http" not in js
    assert "window.JarvisDrive = Object.freeze(" in js


async def test_drive_section_has_the_three_steps_copy_and_not_offered_line(
    client: AsyncClient,
) -> None:
    js = (await client.get("/static/console-drive.js")).text
    assert "Open the folder in Google Drive and press Share." in js
    assert "Paste JARVIS\\'s address (Copy above) into the box." in js
    assert "Choose Viewer, then press Send." in js
    assert "'Copy'" in js and "navigator.clipboard.writeText" in js
    assert "not offered: shared by another account" in js
    assert "aria-pressed" in js and "'On' : 'Off'" in js  # the state is said in words


async def test_page_loads_the_drive_script_after_the_console(client: AsyncClient) -> None:
    html = (await client.get("/")).text
    assert '<dialog class="bdialog" id="driveDialog" role="alertdialog"' in html  # FE-1
    assert 'id="driveDialogNo" type="button">Not now</button>' in html
    assert '<script src="/static/console-drive.js" defer></script>' in html
    assert '<link rel="stylesheet" href="/static/console-drive.css">' in html
    assert html.index('src="/static/console.js"') < html.index('src="/static/console-drive.js"')


def test_a_switched_on_folder_jarvis_cannot_read_says_so_truthfully() -> None:
    """Review F3: never "nothing in it can be read" while JARVIS can; the switch is the truth."""
    js = (ROOT / "src/jarvis/api/static/console-drive.js").read_text(encoding="utf-8")
    assert "nothing in it can be read" not in js and "it.shared" not in js
    assert "readable: it.readable !== false" in js
    assert "Switched on, but JARVIS can\\'t currently read it" in js
    assert "f.confirmed && f.readable" in js  # "N in use" counts only what JARVIS can read


def test_no_dollar_sign_in_drive_strings() -> None:
    js = (ROOT / "src/jarvis/api/static/console-drive.js").read_text(encoding="utf-8")
    for lit in _visible_strings(js):
        assert "$" not in re.sub(r"\$\{", "", lit), lit[:80]


def test_drive_loads_only_when_integrations_opens() -> None:
    js = (ROOT / "src/jarvis/api/static/console-drive.js").read_text(encoding="utf-8")
    assert "d.id === 'integrations' && d.open" in js
    # never on page load: Google is asked only when the owner looks (the panel is open)
    assert "jarvis:ready', () => { if (integOpen()) load(false); }" in js
    assert "window.JarvisDeck.isOpen('integrations')" in js
    # review FE-9: a script arriving after jarvis:ready asks JarvisConsole.ready() too
    assert "C.ready() && integOpen()) load(false);" in js


def test_switching_a_folder_on_asks_first_and_off_is_one_tap() -> None:
    """Review FE-1: a native modal names the folder (textContent) and says JARVIS will read its
    files and send what it reads to Claude; switching off sends at once."""
    js = (ROOT / "src/jarvis/api/static/console-drive.js").read_text(encoding="utf-8")
    assert "if (f.confirmed) { setUse(f, false); return; }" in js
    assert "if (await askOn(f, trigger)) setUse(f, true);" in js
    assert "dlg.showModal();" in js and "$('driveDialogNo').focus();" in js
    assert "JARVIS will be able to read the files in " in js
    assert "sends what it reads to the brain (Claude)" in js
