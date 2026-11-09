# tests/test_r1_persona.py -- R1 I1: persona p4.6 (the Telegram trailer, groceries, parcels,
# family calendars, mail aloud, Activity).
from __future__ import annotations

from typing import Any

import pytest

from jarvis.core import prompts as p

KW: dict[str, Any] = {"tz": "Asia/Kolkata", "session_id": "s", "turn_index": 1}


def test_persona_is_p4_6() -> None:
    assert p.PERSONA_VERSION == "p4.9"


def test_the_telegram_rule_says_what_telegram_can_and_cannot_do() -> None:
    r = p.TELEGRAM_RULE
    assert "plain text" in r.lower() and "markdown" in r.lower()
    assert "120 words" in r
    assert "console" in r
    assert "approv" in r.lower()  # nothing irreversible is approved here
    assert "off by default" in r.lower() and "email" in r.lower()
    assert "never paste" in r.lower()


def test_the_telegram_rule_is_short_and_ascii() -> None:
    assert len(p.TELEGRAM_RULE.split()) <= 120
    assert p.TELEGRAM_RULE.isascii()


@pytest.mark.parametrize("channel", ["text", "voice"])
def test_only_a_telegram_turn_gets_the_telegram_rule(channel: str) -> None:
    assert p.TELEGRAM_RULE not in p.build_trailer(channel=channel, **KW)  # type: ignore[arg-type]
    assert p.TELEGRAM_RULE in p.build_trailer(channel="telegram", **KW)


def _prompt() -> str:
    return p.build_system_prompt(honorific="Sir")


@pytest.mark.parametrize(
    "rule",
    [p.GROCERY_RULES, p.PACKAGES_RULE, p.FAMILY_RULES, p.MAIL_ALOUD_RULE, p.ACTIVITY_RULE],
)
def test_each_r1_paragraph_is_in_the_prompt_and_ascii(rule: str) -> None:
    assert rule in _prompt()
    assert rule.isascii()


def test_groceries_go_to_grocery_tools_not_tasks() -> None:
    r = p.GROCERY_RULES
    assert "grocery_add" in r and "never\n  task_add" in r
    assert "merged" in r and "quantity" in r
    assert "spoken" in r and "other people's content" in r
    assert 'Grant next to "To-do list"' in r


def test_parcels_use_the_tracker_and_never_follow_links() -> None:
    r = p.PACKAGES_RULE
    assert "gmail_track_packages" in r and "carrier" in r and "expected date" in r
    assert "never open" in r and "link" in r


def test_family_calendars_are_read_only_and_adding_asks() -> None:
    r = p.FAMILY_RULES
    assert "read-only" in r and "family_event_add" in r and "asks first" in r
    assert '"Family" list' in r and "someone else's words" in r


def test_mail_aloud_uses_the_digest_and_never_reveals_withheld_items() -> None:
    r = p.MAIL_ALOUD_RULE
    assert "gmail_unread_digest" in r and "masked" in r
    assert "withheld" in r and "never their numbers" in r


def test_activity_points_to_the_panel_and_offers_undo_for_deletes_only() -> None:
    r = p.ACTIVITY_RULE
    assert "Activity panel" in r and "deleted_restore" in r and "cannot be undone" in r


def test_activity_undo_is_only_for_undoable_deletes_and_the_console_panel() -> None:
    r = " ".join(p.ACTIVITY_RULE.split())
    assert "the console's Activity panel" in r
    assert "Deleting and undo" in r and "undo-able delete" in r
    assert "A delete can be undone" not in r


def test_the_p46_comment_lists_every_new_paragraph() -> None:
    import inspect

    head = inspect.getsource(p).split("PERSONA_VERSION =")[0]
    note = head[head.index("# p4.6") :]
    for word in ("Telegram", "grocer", "parcel", "family", "aloud", "Activity"):
        assert word.lower() in note.lower(), word
