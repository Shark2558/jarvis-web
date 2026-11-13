# tests/test_r7_d_console.py -- R7 Part D's console files, read as text (docs/plans/r7-mobile.md D0,
# D19; BRIEF-COMMON section 5): ASCII source, textContent only, a stylesheet that only places
# things (no colour, font, radius or shadow of its own, at most 150 lines), the voice command
# `sos.open` hears exactly the R7 phrases and only opens the sheet, the sheet's send is the one
# request that carries a place and it goes in a POST body, and nothing asks before sign-in.
from __future__ import annotations

import re
from pathlib import Path

from jarvis.voice.commands import R7_PHRASES

STATIC = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "api" / "static"
SOS_JS = (STATIC / "console-r7-sos.js").read_text(encoding="utf-8")
WATCH_JS = (STATIC / "console-helpers-watch.js").read_text(encoding="utf-8")
CSS = (STATIC / "console-r7-sos.css").read_text(encoding="utf-8")


def test_ascii_source_and_text_content_only() -> None:
    for name, text in (("sos", SOS_JS), ("watch", WATCH_JS), ("css", CSS)):
        assert text.isascii(), name
    for text in (SOS_JS, WATCH_JS):
        assert "innerHTML" not in text and "insertAdjacentHTML" not in text
        assert "eval(" not in text and "new Function" not in text
        assert "fetch(" not in text  # the console's own transport only


def test_the_stylesheet_only_places_things() -> None:
    assert len(CSS.splitlines()) <= 150
    body = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", body)  # no colour of its own
    for prop in ("font", "font-family", "border-radius", "box-shadow", "background", "color"):
        assert not re.search(rf"(?<![-\w]){prop}\s*:", body), prop
    assert "var(--line-2)" in body  # an existing token where a line is drawn


def test_the_voice_command_hears_the_r7_phrases_and_only_opens_the_sheet() -> None:
    listed = re.search(r"const VOICE = \[([^\]]*)\]", SOS_JS)
    assert listed is not None
    js = re.findall(r"'([^']+)'", listed.group(1))
    assert js == [p.lower() for p in R7_PHRASES["sos.open"]]
    run = SOS_JS[SOS_JS.index("V.register('sos.open'") :]
    run = run[: run.index("\n")]
    assert "openSheet()" in run and "send(" not in run and "countdown(" not in run


def test_the_one_request_with_a_place_is_a_post_body() -> None:
    sends = re.findall(r"api\('/v1/sos/send'[^)]*\)", SOS_JS)
    assert sends == ["api('/v1/sos/send', { method: 'POST', body })"]
    assert "lat_e6" in SOS_JS and "?lat" not in SOS_JS and "&lat" not in SOS_JS
    assert "console.log" not in SOS_JS  # never logs a place


def test_a_cancel_clears_every_timer_before_anything_is_sent() -> None:
    cancel = SOS_JS[SOS_JS.index("function cancel()") :]
    cancel = cancel[: cancel.index("\n}\n")]
    assert "clearTimeout(S.hold)" in cancel and "clearInterval(S.tick)" in cancel
    assert "api(" not in cancel


def test_nothing_is_asked_before_sign_in() -> None:
    for fn, ask in (
        ("async function refreshCard()", "api("),
        ("async function openSheet()", "loadSheet("),
    ):
        body = SOS_JS[SOS_JS.index(fn) :]
        body = body[: body.index("\n}\n")]
        assert "signedIn()" in body[: body.index(ask)], fn
    # the sheet's read lives in loadSheet(); it is reached only from openSheet() (after that check)
    # and from a countdown, which a hold starts only when signed in (begin() checks it)
    assert SOS_JS.count("loadSheet(") == 3  # its definition and its two callers
    assert "if (S.phase !== 'idle' || !signedIn()) return false;" in SOS_JS
    load = WATCH_JS[WATCH_JS.index("async function load()") :]
    assert load.index("signedIn()") < load.index("H.api(")
