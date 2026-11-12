# tests/test_r11_1_d_console.py -- R11.1 Part D: static checks on the console pieces (the real
# behaviour is tests/browser/test_r11_1_d_look.py). O8: each profile is a card with its own real
# link and "Open next"; "Open all" is gone and no `window.open` result is ever counted. O11: a
# token being read says "Checking..." on its chip. Every module is ASCII, `textContent` only, and
# its stylesheet only places things (plan D0).
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "api" / "static"


def _src(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


# ---- O11: the Vitals chip ------------------------------------------------------------------------
def test_a_row_that_is_being_read_says_checking_on_its_chip() -> None:
    js = _src("console-vitals.js")
    assert "checking: o.checking === true" in js  # only the server's own flag
    assert "'Checking\\u2026'" in js and "chip(it.status, it.checking && !slow)" in js
    assert js.isascii() and len(js.splitlines()) <= 400


def test_a_checking_board_is_read_again_until_it_answers_for_a_bounded_time() -> None:
    """Code review M4 (was: at most three looks, so a slow read left "Checking..." up for good).
    The behaviour is in tests/browser/test_r11_1_d_look.py; here the bound and the words."""
    js = _src("console-vitals.js")
    assert re.search(r"FOLLOW_MS = [1-5]000\b", js) and "FOLLOW_FOR_MS = 45 * 1000" in js
    assert "now - S.followSince < FOLLOW_FOR_MS" in js and "clearTimeout(S.followTimer)" in js
    assert "const SLOW = 'GitHub didn\\'t answer; press Refresh.';" in js
    assert "load(true, true)" in js  # his Refresh follows from the start again


# ---- O8: profile cards (the behaviour is in the browser test) ------------------------------------
def test_the_people_script_has_cards_with_their_own_links_and_no_open_all() -> None:
    js = _src("console-people.js")
    assert "window.open" not in js and "Open all" not in js
    assert "function profileCard(p)" in js and "'Open in browser'" in js and "'Open next'" in js
    assert "a.target = '_blank'; a.rel = 'noopener noreferrer';" in js
    assert "iframe" not in js.lower()  # no page is framed
    assert js.isascii() and "innerHTML" not in js and len(js.splitlines()) <= 400


# ---- O9: "Research a picture" --------------------------------------------------------------------
def test_the_look_module_is_ascii_text_only_and_small() -> None:
    js = _src("console-r111-look.js")
    assert js.isascii() and len(js.splitlines()) <= 200
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert banned not in js
    assert "window.open" not in js and "fetch(" not in js  # the console's own transport only
    assert not re.search(r"""['"]https?://""", js)  # nothing remote is loaded or linked by it
    assert "window.JarvisFixes" in js and "F.part('look'," in js


def test_a_source_is_a_link_only_when_it_is_plain_https() -> None:
    js = _src("console-r111-look.js")
    assert "u.protocol !== 'https:' || u.username || u.password" in js
    assert "a.target = '_blank'; a.rel = 'noopener noreferrer';" in js
    assert "u.hostname" in js  # the site shown is the link's own, not a label the server sent


def test_the_block_says_what_it_does_not_do_and_only_offers_a_name() -> None:
    js = _src("console-r111-look.js")
    assert "I don\\'t identify people from pictures." in js
    assert "'Put this name in the People box'" in js
    offer = js.split("function offerRow(name, caption)", 1)[1].split("\nfunction ", 1)[0]
    assert "F.api(" not in offer  # the offer itself looks nothing up: he presses Research


def test_the_block_asks_the_server_nothing_before_sign_in() -> None:
    """A call made before sign-in is answered 401, and the console's transport answers a 401 by
    showing the sign-in gate: fired at load, it can land just after the owner has signed in and
    throw him back to the gate. So the status is read only once `JarvisConsole.ready()` says he
    is in, as every other panel script does."""
    js = _src("console-r111-look.js")
    assert "const signedIn = () =>" in js and "c.ready()" in js
    assert "if (!goBtn || !signedIn()) return;" in js  # status() itself refuses, whoever calls it
    build = js.split("function build()", 1)[1].split("\nif (F) {", 1)[0]
    assert "status()" not in build.replace("if (signedIn()) status();", "")
    assert "document.addEventListener('jarvis:ready', status);" in js


def test_the_stylesheets_only_place_things() -> None:
    """plan D0: no new colours, fonts, radii or shadows; tokens and existing components only."""
    for name, limit in (("console-r111-look.css", 150), ("console-people.css", 60)):
        css = re.sub(r"/\*.*?\*/", "", _src(name), flags=re.S)
        assert len(_src(name).splitlines()) <= limit, name
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", css), name
        for banned in ("font-family", "font:", "border-radius", "box-shadow", "@import", "url("):
            assert banned not in css, (name, banned)
        colours = set(re.findall(r"(?:color|background|border[a-z-]*|outline):[^;}]*", css))
        assert all("var(--" in c or c.endswith(("none", ":0")) for c in colours), colours
