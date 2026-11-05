# tests/test_things_console.py -- the Things panel and the Drive inbox row, as static contracts
# (served once I1 lists them in APP_ASSETS, so these read the files): no HTML sinks, the console's
# transport only, textContent, ASCII source, <= 800 lines, no dollar signs, plain words.
from __future__ import annotations

from pathlib import Path

from test_console_assets import _sinks  # same directory (pytest prepend import)

STATIC = Path(__file__).resolve().parents[1] / "src/jarvis/api/static"
JS = (STATIC / "console-things.js").read_text(encoding="utf-8")
CSS = (STATIC / "console-things.css").read_text(encoding="utf-8")
DRIVE = (STATIC / "console-drive.js").read_text(encoding="utf-8")


def test_things_script_never_parses_server_text_as_html() -> None:
    assert _sinks(JS) == [] and _sinks(DRIVE) == []
    assert "textContent" in JS and "fetch(" not in JS and "XMLHttpRequest" not in JS
    assert "eval(" not in JS and "http" not in JS and "import " not in JS


def test_sources_are_ascii_and_small_and_use_no_dollar_amounts() -> None:
    for name in ("console-things.js", "console-things.css", "console-drive.js"):
        text = (STATIC / name).read_text(encoding="utf-8")
        assert text.isascii(), name
        assert len(text.splitlines()) <= 800, name
    assert "$" not in CSS.replace("${", "") and "₹" not in JS


def test_things_calls_only_its_own_and_the_bins_routes() -> None:
    for route in (
        "'/v1/things'",
        "'/v1/things/' + t.id + '/history'",
        "'/v1/deleted/' + undoId + '/restore'",
    ):
        assert route in JS
    assert "method: 'DELETE'" in JS and "method: 'PATCH'" in JS and "method: 'POST'" in JS


def test_things_has_search_first_confirm_dialog_with_focus_trap_and_undo() -> None:
    assert JS.index("qIn = mk(") < JS.index("nameIn = mk(")  # search box before the quick add
    assert "showModal" in JS and "e.key !== 'Tab'" in JS and "'cancel'" in JS
    assert "Undo" in JS and "Recently deleted" in JS
    assert "Moved\\u2026" in JS and "'History'" in JS and "'Delete'" in JS
    assert "aria-live" in JS and "aria-label" in JS


def test_the_drive_inbox_row_confirms_and_can_switch_off() -> None:
    assert "'/v1/vault/inbox'" in DRIVE and "Use for DigiLocker import" in DRIVE
    assert "askOn(f, b, true)" in DRIVE and "Switch off" in DRIVE
    assert "will never read this folder" in DRIVE and "delete them yourself" in DRIVE
    assert "inbox_wired" in DRIVE  # asked only when the server has the inbox
