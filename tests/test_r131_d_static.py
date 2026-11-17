# tests/test_r131_d_static.py -- R13.1 Part D's static rules (docs/plans/r13-1-try-on.md D1, D9,
# D12, D21, D22; BRIEF-D sections 1-2), read from the console's own files, no browser:
#   - the fixed lists D draws are the server's (NEW_TYPES, R13's colours): one source
#   - D's modules reach the server only through JarvisConsole.api or the door (no fetch, XHR,
#     beacon or socket of their own), write the page by textContent only, keep nothing on the
#     device, never import three or name the engine's files, and are ASCII
#   - a photo is chosen from a file only (JPEG or PNG, no `capture`), and nothing asks for or
#     opens a web address (JARVIS fetches none, D22)
#   - the engine is reached through window.JarvisTryOn3D only; the loads other tests pin stay
#   - the stage's sizes and the 44 px targets live in console-tryon.css, which only places things
#   - a request id is `tq_` + 16 hex from the browser's own random source
from __future__ import annotations

import re
from pathlib import Path

import pytest

from jarvis.wardrobe.model import COLOURS
from jarvis.wardrobe.tryon.model import NEW_TYPES

STATIC = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "api" / "static"
D_JS = (
    "console-tryon.js", "console-tryon-list.js", "console-tryon-me.js", "console-tryon-photo.js",
    "console-tryon-card.js",
)  # fmt: skip


def _text(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _code(name: str) -> str:
    return re.sub(r"//[^\n]*|/\*.*?\*/", "", _text(name), flags=re.S)  # comments say the rules


def _js_list(code: str, name: str) -> list[str]:
    m = re.search(rf"export const {name} = Object\.freeze\(\[(.*?)\]\)", code, flags=re.S)
    assert m, name
    return re.findall(r"'([a-z_]+)'", m.group(1))


def test_the_garments_type_and_colour_lists_are_the_servers() -> None:
    code = _code("console-tryon-me.js")
    assert _js_list(code, "NEW_TYPES") == list(NEW_TYPES)
    assert _js_list(code, "COLOURS") == list(COLOURS)


@pytest.mark.parametrize("name", D_JS)
def test_ds_modules_send_nothing_of_their_own_and_write_text_only(name: str) -> None:
    code = _code(name)
    for bad in (
        "fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "EventSource", "localStorage",
        "sessionStorage", "indexedDB", "caches.", "innerHTML", "outerHTML", "insertAdjacentHTML",
        "document.write", "eval(", "new Function", "postMessage", "window.open(",
    ):  # fmt: skip
        assert bad not in code, (name, bad)
    assert not re.search(r"vendor/three|three\.module|from\s+['\"]three", code), name  # B's engine
    assert not re.search(r"https?://", code), name  # no address is ever opened or fetched
    assert _text(name).isascii(), name


@pytest.mark.parametrize("name", D_JS)
def test_ds_modules_call_only_jarvis_paths_through_the_consoles_api(name: str) -> None:
    code = _code(name)
    for path in re.findall(r"""api\(\s*['"`]([^'"`]+)""", code):
        assert path.startswith(("/v1/tryon", "/v1/seeme", "/v1/wardrobe", "/v1/outfits")), path


def test_a_photo_is_chosen_from_a_file_and_no_web_address_is_asked_for() -> None:
    code = _code("console-tryon-me.js")
    # one picker(): the console's own button over a hidden input (review D-1 M4)
    assert code.count("input.type = 'file'; input.accept = 'image/jpeg,image/png';") == 1
    assert "input.hidden = true; input.tabIndex = -1;" in code
    assert code.count("picker('trMyPhoto', ") == 1 and code.count("picker('trGarment', ") == 1
    assert 'input[type="file"]' not in _text("console-tryon.css")  # no raw file input is styled
    assert "capture" not in code  # the front camera can't take a full-length photo (D12)
    for name in D_JS:
        assert "'url'" not in _code(name) and "href" not in _code(name).replace("a.href = url", "")


def test_the_engine_is_reached_through_its_contract_and_the_pinned_loads_stay() -> None:
    main = _code("console-tryon.js")
    for spec in ("'./console-tryon-list.js'", "'./console-tryon-me.js'", "'./console-tryon-3d.js'"):
        assert spec in main, spec
    assert "'./console-tryon-photo.js'" in _code("console-tryon-me.js")
    assert "window.JarvisTryOn3D" in main
    calls = set(re.findall(r"\b(?:v\.stage|st)\.(\w+)\(", main))
    contract = {"show", "view", "spin", "zoom", "closer", "snapshot", "stats", "dispose"}
    assert calls == contract, calls  # every Stage method of the contract, and nothing else
    assert "'./console-tryon-glb.js'" not in main and "'./console-tryon-cloth.js'" not in main


def test_the_stage_and_its_targets_are_placed_by_the_css() -> None:
    css = _text("console-tryon.css")
    assert ".tr-stage{position:relative;height:480px;" in css  # a laptop
    phone = css[css.index("@media (max-width:899px)") :]
    assert ".tr-stage{height:56vh}" in phone  # a phone
    assert ".tr-sec .btn.sact,.tr-card .btn.sact{height:auto;min-height:44px;min-width:44px}" in css


def test_a_request_id_is_tq_and_16_hex_from_the_browsers_random_source() -> None:
    code = _code("console-tryon-me.js")
    assert "const b = new Uint8Array(8); crypto.getRandomValues(b);" in code
    assert "'tq_' + Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('')" in code
    assert "Math.random" not in code


def test_cancel_and_escape_send_nothing_and_make_the_picture_sends_the_contracts_body() -> None:
    code = _code("console-tryon-me.js")
    assert "if (go !== true) { say('', 'Nothing was sent.'); return; }" in code
    assert "d.addEventListener('close', closed);" in code  # Escape: closed, answered with nothing
    assert "if (d.open) return; d.removeEventListener('close', closed); resolve(null);" in code
    body = "{ garment: M.garment.id, pieces, confirm_cost: true, inr_shown: est.typical_inr, "
    assert body + "request_id: id }" in code  # PictureIn's five fields, nothing more
    # one id per confirmed picture (review D-1 M1): kept only while the answer may have been lost
    assert "M.pending = { key, id: requestId(), again: false }" in code
    assert "e.status >= 500 || e.status === 408 || e.code === 'busy'" in code


def test_the_card_registers_once_and_reads_only_the_card() -> None:
    code = _code("console-tryon-card.js")
    assert code.count("window.JarvisTryOnCard = Object.freeze({ cards, garment })") == 1
    assert "const PIECE = /^wi_[0-9a-f]{12}$/;" in code
    assert "api(" not in code and "door" not in code  # it asks the server for nothing itself
