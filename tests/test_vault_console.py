# tests/test_vault_console.py -- the Vault panel as a static contract: R2 review M3 (a reply never
# makes a closed Vault panel fetch /v1/vault, which decrypts the index and runs the reminders
# check), plus ASCII source within 800 lines and the console's transport only.
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src/jarvis/api/static"
JS = (STATIC / "console-vault.js").read_text(encoding="utf-8")


def _handler(event: str) -> str:
    """The one-line listener for `event` (the panel scripts keep each listener on one line)."""
    (line,) = [x for x in JS.splitlines() if f"'{event}'" in x and "addEventListener" in x]
    return line


def test_a_reply_refreshes_the_vault_only_while_its_panel_is_open() -> None:
    on_reply = _handler("jarvis:reply")
    assert "isOpen('vault')" in on_reply
    assert re.search(r"isOpen\('vault'\)[^;]*\)\s*load\(true\)", on_reply)
    assert "else S.loadedAt = 0" in on_reply  # closed: the next open fetches fresh


def test_vault_script_keeps_the_console_rules() -> None:
    assert JS.isascii() and len(JS.splitlines()) <= 800
    assert "fetch(" not in JS and "eval(" not in JS and "innerHTML" not in JS
