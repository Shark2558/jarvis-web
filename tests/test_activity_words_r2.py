# tests/test_activity_words_r2.py -- R2 D13 (I1): Activity is kept in clear for 7 days, so a tool
# with fixed `activity_words` is described by those words only (reads and writes alike), never by
# its card text or arguments; kb_remove and belongings_remove are deletes (their Undo shows).
from __future__ import annotations

from typing import Any

import pytest

from jarvis.activity.words import describe, kind_of, undo_note
from jarvis.core.guardrails import ActionRisk
from jarvis.tools.base import Tool
from jarvis.tools.registry import ToolRegistry

R1, R2 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE
SECRET = "the spare key is under the blue flowerpot"


def _reg(name: str, words: str | None, risk: ActionRisk = R2) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        Tool(
            name,
            "test",
            {"type": "object", "properties": {"text": {"type": "string"}}},
            risk,
            lambda a: a,
            summarize=lambda a: f"Save the note: {a.get('text', '')}",
            activity_words=words,
        )
    )
    return reg


def test_a_write_with_fixed_words_never_shows_its_card_text() -> None:
    reg = _reg("kb_add_note", "Saved a note")
    kind, words = describe("kb_add_note", {"text": SECRET}, R2, "done", reg)
    assert (kind, words) == ("write", "Saved a note")
    assert "flowerpot" not in words


def test_a_read_with_fixed_words_uses_them_instead_of_the_prefix_table() -> None:
    reg = _reg("vault_list", "Looked at your vault list", R1)
    assert describe("vault_list", {}, R1, "done", reg) == ("read", "Looked at your vault list")


@pytest.mark.parametrize(
    ("outcome", "want"),
    [
        ("waiting", "Waiting for your OK: Save a note"),
        ("refused", "Blocked by your settings: Save a note"),
        ("failed", "Didn't work: Save a note"),
        ("declined", "You declined: Save a note"),
    ],
)
def test_unfinished_rows_say_the_fixed_words_as_an_imperative(outcome: str, want: str) -> None:
    reg = _reg("kb_add_note", "Saved a note")
    assert describe("kb_add_note", {"text": SECRET}, R2, outcome, reg)[1] == want


@pytest.mark.parametrize(
    ("past", "imperative"),
    [
        ("Looked at your vault list", "Look at your vault list"),
        ("Changed a vault date", "Change a vault date"),
        ("Searched your notes", "Search your notes"),
        ("Opened a note", "Open a note"),
        ("Saved a link", "Save a link"),
        ("Deleted a note", "Delete a note"),
        ("Looked up where something is kept", "Look up where something is kept"),
        ("Noted where something is kept", "Note where something is kept"),
        ("Forgot where something is kept", "Forget where something is kept"),
    ],
)
def test_every_r2_verb_has_its_imperative(past: str, imperative: str) -> None:
    reg = _reg("x_tool", past)
    assert describe("x_tool", {}, R2, "waiting", reg)[1] == "Waiting for your OK: " + imperative


def test_an_unknown_verb_is_kept_as_it_is() -> None:
    reg = _reg("x_tool", "Tidied the shelf")
    assert describe("x_tool", {}, R2, "waiting", reg)[1] == "Waiting for your OK: Tidied the shelf"


def test_tools_without_fixed_words_keep_their_card_text() -> None:
    reg = _reg("calendar_add", None)
    assert describe("calendar_add", {"text": "Lunch"}, R2, "done", reg)[1] == "Save the note: Lunch"


@pytest.mark.parametrize("tool", ["kb_remove", "belongings_remove"])
def test_r2_removes_are_deletes(tool: str) -> None:
    assert kind_of(tool, R2) == "delete"
    assert undo_note(tool, "delete", "done", has_bin_copy=True) == ""


def test_every_r2_tool_declares_fixed_words() -> None:
    from kb_fakes import build_rig

    from jarvis.belongings.service import BelongingsService
    from jarvis.belongings.store import BelongingsStore
    from jarvis.belongings.tools import belongings_tools
    from jarvis.kb.tools import notes_tools
    from jarvis.keyring import Keyring
    from jarvis.storage.docs import MemoryDocs
    from jarvis.vault.tools import vault_tools

    ring = Keyring(bytes(range(1, 33)))
    tools: list[Any] = [
        *notes_tools(build_rig().svc),
        *belongings_tools(BelongingsService(BelongingsStore(MemoryDocs(), ring))),
        *vault_tools(None),  # type: ignore[arg-type]  # only the declarations are read
    ]
    names = {t.name for t in tools}
    assert {"vault_list", "kb_add_note", "belongings_put"} <= names
    for t in tools:
        assert t.activity_words and t.activity_words.isascii(), t.name
