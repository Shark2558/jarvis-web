# tests/test_window.py
from __future__ import annotations

from jarvis.core.models import Turn
from jarvis.core.window import build_window
from jarvis.llm.base import Role


def _t(role: Role, content: str) -> Turn:
    return Turn(role=role, content=content)


def test_window_respects_max_turns_and_starts_with_user() -> None:
    turns = []
    for i in range(10):
        turns.append(_t(Role.USER, f"u{i}"))
        turns.append(_t(Role.ASSISTANT, f"a{i}"))
    win = build_window(turns, max_turns=5, max_chars=10_000)
    # 5 most recent would start with an assistant turn (a7); it must be dropped
    assert [m.content for m in win] == ["u8", "a8", "u9", "a9"]
    assert win[0].role is Role.USER


def test_window_respects_char_budget() -> None:
    turns = [_t(Role.USER, "x" * 100), _t(Role.ASSISTANT, "y" * 100), _t(Role.USER, "z" * 100)]
    win = build_window(turns, max_turns=50, max_chars=150)
    assert [m.content for m in win] == ["z" * 100]


def test_window_collapses_same_role_runs_and_skips_empty() -> None:
    turns = [
        _t(Role.USER, "first"),
        _t(Role.USER, "second"),  # e.g. previous assistant turn failed and was never saved
        _t(Role.ASSISTANT, "   "),
        _t(Role.ASSISTANT, "reply"),
    ]
    win = build_window(turns, max_turns=50, max_chars=10_000)
    assert len(win) == 2
    assert win[0].content == "first\n\nsecond"
    assert win[1].content == "reply"


def test_window_empty_input() -> None:
    assert build_window([], max_turns=5, max_chars=100) == []
