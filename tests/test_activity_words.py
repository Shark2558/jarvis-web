# tests/test_activity_words.py -- R1 B: the plain-words line of one Activity row and the reason
# a row has no Undo (plan D7/D8). Reads never show query text; writes use the tool's own card text.
from __future__ import annotations

import pytest

from jarvis.activity.words import describe, kind_of, undo_note
from jarvis.core.guardrails import ActionRisk
from jarvis.tools.base import Tool
from jarvis.tools.registry import ToolRegistry

R1, R2, R3 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE, ActionRisk.IRREVERSIBLE


async def _noop(**_: object) -> dict[str, object]:
    return {}


def _reg() -> ToolRegistry:
    reg = ToolRegistry()
    for name, risk, tpl in [
        ("gmail_search", R1, "Search mail for {query}"),
        ("calendar_list_events", R1, "List events"),
        ("create_reminder", R2, "Remind you: {text}"),
        ("gmail_send", R3, "Send an email to {to}"),
        ("calendar_delete_event", R2, "Delete an event"),
    ]:
        reg.register(
            Tool(
                name=name,
                description="d",
                input_schema={"type": "object", "properties": {}},
                risk=risk,
                run=_noop,
                summary_template=tpl,
            )
        )
    return reg


def test_a_read_shows_a_fixed_verb_and_never_the_query() -> None:
    kind, words = describe("gmail_search", {"query": "from:bank OTP"}, R1, "done", _reg())
    assert kind == "read" and words == "Searched your email"
    assert "bank" not in words and "OTP" not in words


def test_a_write_uses_the_tools_own_card_text() -> None:
    kind, words = describe("create_reminder", {"text": "call mum"}, R2, "done", _reg())
    assert kind == "write" and words == "Remind you: call mum"


@pytest.mark.parametrize(
    ("outcome", "prefix"),
    [
        ("waiting", "Waiting for your OK: "),
        ("refused", "Blocked by your settings: "),
        ("failed", "Didn't work: "),
        ("declined", "You declined: "),
    ],
)
def test_other_outcomes_get_a_plain_prefix(outcome: str, prefix: str) -> None:
    _, words = describe("gmail_send", {"to": "a@b.com"}, R3, outcome, _reg())
    assert words == prefix + "Send an email to a@b.com"


def test_a_read_that_did_not_run_uses_the_imperative() -> None:
    _, words = describe("calendar_list_events", {}, R1, "refused", _reg())
    assert words == "Blocked by your settings: Look at your calendar"


def test_unknown_tool_and_hostile_name_are_one_clean_line() -> None:
    kind, words = describe("zz\nevil\u202e" + "x" * 300, {}, R2, "done", _reg())
    assert "\n" not in words and "\u202e" not in words and len(words) <= 300
    assert kind == "write"


@pytest.mark.parametrize(
    ("tool", "risk", "kind"),
    [
        ("calendar_delete_event", R2, "delete"),
        ("task_delete", R3, "delete"),
        ("memory_forget", R2, "delete"),
        ("gmail_send", R3, "send"),
        ("send_message", R3, "send"),
        ("gmail_create_draft", R2, "draft"),
        ("whatsapp_draft", R1, "draft"),
        ("deleted_restore", R2, "restore"),
        ("task_add", R2, "write"),
        ("web_search", R1, "read"),
    ],
)
def test_kind_of(tool: str, risk: ActionRisk, kind: str) -> None:
    assert kind_of(tool, risk) == kind


@pytest.mark.parametrize(
    ("tool", "kind", "text"),
    [
        ("task_add", "write", "Can't be undone from here"),
        ("gmail_create_draft", "draft", "In Gmail Drafts"),
        ("whatsapp_draft", "draft", "Nothing was sent"),
        ("gmail_send", "send", "Sent \u2014 can't be undone"),
        ("memory_save", "write", "Remove it in Memory"),
        ("deleted_restore", "restore", "Delete it again if you didn't want it back"),
    ],
)
def test_undo_note_says_why_there_is_no_undo(tool: str, kind: str, text: str) -> None:
    assert text in undo_note(tool, kind, "done")


def test_undo_note_for_a_read_and_for_unfinished_calls() -> None:
    assert undo_note("web_search", "read", "done") == ""
    assert undo_note("gmail_send", "send", "waiting") == "Nothing has happened yet"
    assert undo_note("gmail_send", "send", "declined") == "Nothing was done"
    assert undo_note("gmail_send", "send", "refused") == "Nothing was done"
