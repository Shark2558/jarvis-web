# tests/test_r8_i_dock.py -- R8 I, "your bar, your way" (docs/plans/r8-vision.md v8.0.4 D13; the
# owner, 28 Nov 2026: "make every icon editable ... drag and drop each item and place it as per my
# requirement. Also, the items I remove should be in the More. I should also have the option to hide
# the bar as well."). The editor (console-dock-edit.js) on the I0 layout model
# (console-dock-layout.js), run in Node: the shipped bar is never written (so the 1920 px bar stays
# byte-identical until he edits it), Put back returns a tab to its shipped place, drops and keyboard
# steps, the shortcuts, the words it says. Then the files' own rules, read as text: the editor alone
# writes the layout's key, nothing asks the server, no HTML is parsed, the stylesheet only places
# things with the console's tokens, and the line budgets hold. The page itself:
# tests/browser/test_r8_dock_edit.py.
from __future__ import annotations

import json
import re
from typing import Any

import pytest
from r8_fakes import STATIC, run_node

EDIT = "console-dock-edit.js"
SHIPPED = [
    "chat",
    "brief",
    "approvals",
    "activity",
    "vault",
    "construct",
    "helpers",
    "camera",
    "calls",
]
NAMES = {
    "chat": "Chat",
    "brief": "Brief",
    "approvals": "Approvals",
    "vitals": "Vitals",
    "construct": "Construct",
    "camera": "Camera",
    "calls": "Calls",
    "helpers": "Helpers",
}


def _ed(call: str, *args: Any) -> Any:
    return run_node(EDIT, call, *args)


def _model(call: str, *args: Any) -> Any:  # the I0 layout model the editor builds on
    return run_node("console-dock-layout.js", call, *args)


def _layout(
    order: list[str], more: list[str] | None = None, hidden: bool = False
) -> dict[str, Any]:
    return {"v": 1, "order": order, "more": more or [], "hidden": hidden}


def _text(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _code(name: str) -> str:
    return re.sub(r"//[^\n]*|/\*.*?\*/", "", _text(name), flags=re.S)


# ---- the shipped bar is never written ------------------------------------------------------------
def test_the_shipped_bar_is_never_written_and_an_edit_is() -> None:
    shipped = _ed("mod.layoutFrom", None, SHIPPED)
    assert shipped == _layout(SHIPPED)
    assert _ed("mod.toStore", SHIPPED, shipped) is None  # nothing kept: the key is removed
    moved = _ed("mod.step", shipped, "camera", -1)
    text = _ed("mod.toStore", SHIPPED, moved)
    assert json.loads(text) == _layout([*SHIPPED[:6], "camera", "helpers", "calls"])
    assert _ed("mod.layoutFrom", text, SHIPPED) == moved  # read back as kept
    hidden = _ed("mod.toStore", SHIPPED, {**shipped, "hidden": True})
    assert json.loads(hidden)["hidden"] is True  # hiding the bar alone is an edit


@pytest.mark.parametrize("text", ["not json", '{"v": 2, "order": []}', "[]", '"x"', "null"])
def test_an_unreadable_saved_layout_is_the_shipped_bar(text: str) -> None:
    assert _ed("mod.layoutFrom", text, SHIPPED) == _layout(SHIPPED)


def test_a_tab_a_later_release_adds_lands_at_the_end_and_none_is_lost() -> None:
    saved = json.dumps(_layout(["camera", "chat", "brief"], ["vault"]))
    drawn = _ed("mod.layoutFrom", saved, [*SHIPPED, "newtab"])
    assert drawn["order"][:3] == ["camera", "chat", "brief"] and drawn["order"][-1] == "newtab"
    assert drawn["more"] == ["vault"]
    assert sorted(drawn["order"] + drawn["more"]) == sorted([*SHIPPED, "newtab"])


# ---- Put back, drops and steps -------------------------------------------------------------------
def test_put_back_returns_a_tab_to_its_shipped_place_and_the_bar_is_shipped_again() -> None:
    off = _model("mod.toMore", _layout(SHIPPED), "construct")
    assert off["more"] == ["construct"] and "construct" not in off["order"]
    back = _ed("mod.putBack", off, "construct", SHIPPED)
    assert back == _layout(SHIPPED)
    assert _ed("mod.toStore", SHIPPED, back) is None  # nothing kept again


def test_put_back_follows_his_order_and_goes_last_when_nothing_after_it_is_on_the_bar() -> None:
    his = _layout(
        ["camera", "chat", "brief", "approvals", "activity", "helpers", "calls"],
        ["vault", "construct"],
    )
    back = _ed("mod.putBack", his, "construct", SHIPPED)
    assert back["order"].index("construct") == back["order"].index("helpers") - 1  # before Helpers
    tail = _layout(["chat", "brief"], ["calls"])
    assert _ed("mod.putBack", tail, "calls", ["chat", "brief", "calls"])["order"] == [
        "chat",
        "brief",
        "calls",
    ]
    assert (
        _ed("mod.putBack", tail, "brief", ["chat", "brief", "calls"]) == tail
    )  # not in More: unchanged


def test_a_drop_lands_before_the_item_under_it_or_after_the_last() -> None:
    bar = _layout(["chat", "brief", "approvals", "vitals", "camera"])
    to_third = _ed("mod.dropTo", bar, "vitals", "approvals", "brief")
    assert to_third["order"] == ["chat", "brief", "vitals", "approvals", "camera"]
    last = _ed("mod.dropTo", bar, "brief", None, "camera")
    assert last["order"] == ["chat", "approvals", "vitals", "camera", "brief"]
    assert _ed("mod.dropTo", bar, "vitals", "vitals", "approvals") == bar  # onto its own place
    assert _ed("mod.dropTo", bar, "vitals", "camera", "vitals") == bar
    assert _ed("mod.dropTo", bar, "nothere", "chat", None) == bar


def test_a_keyboard_step_moves_one_place_and_stops_at_either_end() -> None:
    bar = _layout(["chat", "brief", "approvals"])
    assert _ed("mod.step", bar, "brief", -1)["order"] == ["brief", "chat", "approvals"]
    assert _ed("mod.step", bar, "brief", 1)["order"] == ["chat", "approvals", "brief"]
    assert _ed("mod.step", bar, "chat", -1) == bar and _ed("mod.step", bar, "approvals", 1) == bar


def test_chat_can_never_be_taken_off_the_bar() -> None:
    bar = _layout(SHIPPED)
    assert _model("mod.toMore", bar, "chat") == bar
    drawn = _ed("mod.layoutFrom", json.dumps(_layout(["brief"], ["chat"])), SHIPPED)
    assert (
        "chat" in drawn["order"] and "chat" not in drawn["more"]
    )  # a hand-edited key can't hide it


@pytest.mark.parametrize(
    ("centres", "at", "want"), [([10, 50, 90], 5, 0), ([10, 50, 90], 49, 1), ([10, 50, 90], 95, 3)]
)
def test_the_drop_slot_is_where_the_pointer_passes_a_centre(
    centres: list[int], at: int, want: int
) -> None:
    assert _ed("mod.slot", centres, at) == want


# ---- the shortcuts and the words -----------------------------------------------------------------
@pytest.mark.parametrize(
    ("keys", "want"),
    [
        ({"ctrlKey": True, "code": "Period"}, "show"),
        ({"ctrlKey": True, "shiftKey": True, "code": "Period"}, "edit"),
        ({"ctrlKey": True, "altKey": True, "code": "Period"}, None),
        ({"metaKey": True, "code": "Period"}, None),
        ({"ctrlKey": True, "code": "Period", "repeat": True}, None),
        ({"ctrlKey": True, "code": "Space"}, None),  # the microphone's keys stay the microphone's
        ({"code": "Period"}, None),
    ],
)
def test_ctrl_dot_shows_the_bar_and_ctrl_shift_dot_edits_it(
    keys: dict[str, Any], want: str | None
) -> None:
    assert _ed("mod.shortcut", keys) == want


def test_the_words_say_where_an_item_lands_in_plain_english() -> None:
    order = ["chat", "brief", "vitals", "approvals", "camera"]
    assert (
        _ed("mod.placeWords", order, "vitals", NAMES)
        == "Vitals is 3rd now, between Brief and Approvals."
    )
    assert _ed("mod.placeWords", order, "chat", NAMES) == "Chat is first now, before Brief."
    assert _ed("mod.placeWords", order, "camera", NAMES) == "Camera is last now, after Approvals."
    assert _ed("mod.dropWords", order, "vitals", NAMES) == (
        "Let go to put Vitals 3rd, between Brief and Approvals. Esc puts it back."
    )
    assert [_ed("mod.ordinal", n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 23)] == [
        *("1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "23rd")
    ]
    assert _ed("mod.listWords", ["Camera", "Calls", "Helpers"]) == "Camera, Calls and Helpers"


def test_the_words_say_what_a_change_did_to_the_room() -> None:
    before, after = ["chat", "construct", "helpers"], ["chat", "helpers", "camera"]
    assert (
        _ed("mod.roomWords", before, after, NAMES, "construct")
        == "Camera has room on the bar again."
    )
    went = _ed("mod.roomWords", ["chat", "camera", "calls"], ["chat"], NAMES, None)
    assert went == "Camera and Calls wait in More: no room for them now."
    assert _ed("mod.noRoomWords", ["calls"], NAMES, False) == "Calls has no room at this width."
    assert _ed("mod.noRoomWords", ["camera", "calls"], NAMES, True) == (
        "Camera and Calls wait in More: no room for them at this width."
    )
    assert _ed("mod.noRoomWords", [], NAMES, True) == ""
    many = _ed("mod.noRoomWords", ["vault", "construct", "helpers", "camera", "calls"], NAMES, True)
    assert many == "5 items wait in More: no room for them at this width."


def test_the_editor_keeps_the_gesture_numbers_of_the_mockup() -> None:
    edit = _code(
        EDIT
    )  # ui-ux-pro-max: a 500 ms long-press, a drag after 8 px (WCAG 2.5.7 has the click way)
    assert "export const LONG_PRESS_MS = 500;" in edit and "export const DRAG_PX = 8;" in edit
    assert "export const SHOW_KEYS = 'Ctrl + .';" in edit
    assert "export const EDIT_KEYS = 'Ctrl + Shift + .';" in edit


# ---- the files' own rules ------------------------------------------------------------------------
def test_only_the_editor_writes_the_layout_and_the_dock_only_looks_for_it() -> None:
    for path in sorted(STATIC.glob("*.js")):
        if "jarvis_dock_layout_v1" in path.read_text(encoding="utf-8"):
            assert path.name in {"console-dock.js", "console-dock-layout.js", EDIT}, path.name
    dock = _code("console-dock.js")
    assert "localStorage.getItem('jarvis_dock_layout_v1') !== null" in dock  # presence only
    assert "setItem" not in dock and "removeItem" not in dock
    edit = _code(EDIT)
    assert "localStorage.setItem(KEY, text)" in edit and "localStorage.removeItem(KEY)" in edit
    layout = _code("console-dock-layout.js")
    assert "localStorage" not in layout  # the model stays pure (I0)


def test_the_editor_asks_the_server_nothing_and_parses_no_html() -> None:
    edit = _code(EDIT)
    for bad in (
        "fetch(",
        "XMLHttpRequest",
        "JarvisConsole",
        "JarvisMobile",
        "sendBeacon",
        "WebSocket",
    ):
        assert bad not in edit, bad
    for sink in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "DOMParser",
        "eval(",
        "new Function",
    ):
        assert sink not in edit and sink not in _code("console-dock.js"), sink
    assert "import(" not in edit  # its one import is the layout model, statically
    assert re.findall(r"from '([^']+)'", edit) == ["./console-dock-layout.js"]


def test_no_new_always_visible_button_and_the_shipped_markup_is_untouched() -> None:
    html = _text("console.html")
    dock = html[html.index('<nav class="dock card"') : html.index("</nav>")]
    assert "dke" not in html and "Edit the bar" not in html  # the page is I0's, as shipped
    assert len(re.findall(r'class="dk', dock)) == 24  # 23 tabs and More, as before R8
    edit = _code(EDIT)
    for way in ("'contextmenu'", "LONG_PRESS_MS", "shortcut(e)", "'themeMenu'"):
        assert way in edit, way  # right-click, long-press, the keys, the settings line


STYLE_PROPS = re.compile(
    r"(?<![-\w])(color|background|background-color|border-color|fill|stroke)\s*:\s*([^;}]+)"
)


def test_the_stylesheet_only_places_things_with_the_consoles_tokens() -> None:
    css = _text("console-dock-edit.css")
    assert len(css.splitlines()) <= 150
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", css)  # no new colour
    for prop, value in STYLE_PROPS.findall(css):
        words = re.sub(r"var\(--[\w-]+(?:,[^)]*)?\)|color-mix\([^;]*\)", "", value)
        assert set(re.findall(r"[a-z-]+", words)) <= {
            "transparent",
            "currentcolor",
            "currentColor",
        }, (prop, value)
    fonts = re.findall(r"font(?:-family)?\s*:\s*([^;}]+)", css)
    for font in fonts:
        families = re.findall(r"var\(--([\w-]+)\)", font)
        assert set(families) <= {"tech", "hud", "font"} and "'" not in font and '"' not in font, (
            font
        )
    radii = set(re.findall(r"border-radius\s*:\s*([^;}]+)", css))
    assert radii <= {
        "50%",
        "var(--r-sm)",
        "var(--r-md)",
        "var(--r-lg)",
        "12px",
        "4px",
        "3px",
        "2px",
    }, radii
    for rule in re.findall(r"([^{}]+)\{", re.sub(r"/\*.*?\*/", "", css, flags=re.S)):
        selectors = [
            s.strip() for s in rule.split(",") if s.strip() and not s.strip().startswith("@")
        ]
        for sel in selectors:  # every rule is the editor's own (dke-), never the console's alone
            assert "dke" in sel or sel.startswith("@media"), sel


def test_the_line_budgets_hold() -> None:
    assert len(_text("console-dock.js").splitlines()) <= 400  # test_console_assets' cap
    assert len(_text(EDIT).splitlines()) <= 800
    assert len(_text("console-dock-edit.css").splitlines()) <= 150
    assert _text(EDIT).isascii() and _text("console-dock-edit.css").isascii()


def test_the_dock_still_describes_every_tab_it_did_and_builds_the_sheet() -> None:
    dock = _text("console-dock.js")
    start = dock.index("const DESCRIBE = {")
    described = re.findall(r"^\s+(\w+): '", dock[start : dock.index("};", start)], re.M)
    assert described[0] == "approvals" and described[-1] == "calls" and "chat" not in described
    assert "window.JarvisDock = Object.freeze({" in dock
    assert "if (sheetHook) document.dispatchEvent(new CustomEvent('jarvis:dock'))" in dock
    assert "const forced = removed.size > 0" in dock or "forced = removed.size > 0" in dock
