# tests/test_voice_speakable.py — slice 9 D6: speakable() is the server's authority on what is
# read aloud (no markdown, code, tables, URLs, emoji, control/bidi chars; ≤ 600 chars).
from __future__ import annotations

import pytest

from jarvis.voice.speakable import LINK_WORDS, MAX_SPEAK_CHARS, speakable


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("Good evening, Sir.", "Good evening, Sir."),
        ("**Done**, Sir.", "Done, Sir."),
        ("This is *quite* _remarkable_.", "This is quite remarkable."),
        ("~~old~~ new plan", "old new plan"),
        ("# Summary\nAll systems nominal.", "Summary. All systems nominal."),
        ("- milk\n- eggs\n- bread", "milk. eggs. bread."),
        ("1. First\n2. Second", "First. Second."),
        ("> quoted line", "quoted line"),
        ("Run `make test` now.", "Run make test now."),
        ("See [the docs](https://example.com/a) please.", "See the docs please."),
        ("Read https://example.com/x?y=1.", f"Read {LINK_WORDS}."),
        ("Visit www.example.org today", f"Visit {LINK_WORDS} today"),
        ("<https://a.example>", LINK_WORDS),
        ("Lovely 😀 day 🎉!", "Lovely day!"),
        ("Hi\u202e there\u2066", "Hi there"),
        ("a\x00b\x07c", "a b c"),
        ("snake_case_name stays", "snake_case_name stays"),
        ("25°C and ₹500", "25°C and ₹500"),
        ("line one\nline two", "line one line two"),
        ("para one\n\npara two", "para one. para two."),
        ("<b>bold</b> text", "bold text"),
        ("3 < 5 and 7 > 2", "3 < 5 and 7 > 2"),
        ("Wait... what? Wow!!", "Wait... what? Wow!!"),
        ("Done. \U0001f389 . Next", "Done. Next"),
    ],
)
def test_shapes_markdown_into_plain_speech(raw: str, want: str) -> None:
    assert speakable(raw) == want


def test_code_blocks_and_tables_are_never_spoken() -> None:
    text = "Here it is:\n```python\nprint('x')\n```\n| a | b |\n|---|---|\n| 1 | 2 |\nThat's all."
    out = speakable(text)
    assert "print" not in out and "|" not in out and "---" not in out
    assert out == "Here it is: That's all."


def test_an_unclosed_fence_hides_everything_after_it() -> None:
    assert speakable("Before.\n```\ncode without end") == "Before."


def test_long_inline_code_is_not_read_out() -> None:
    out = speakable("Use `" + "x" * 60 + "` here.")
    assert "xxxx" not in out and "on screen" in out


@pytest.mark.parametrize(
    "raw", ["", "   ", "```\nonly code\n```", "😀🎉", "| a | b |\n|---|---|", "***", "\u200b\u200e"]
)
def test_nothing_speakable_gives_empty(raw: str) -> None:
    assert speakable(raw) == ""


def test_caps_at_a_sentence_boundary() -> None:
    sentence = "This sentence has exactly some words in it. "
    out = speakable(sentence * 40)
    assert len(out) <= MAX_SPEAK_CHARS
    assert out.endswith("in it.") and len(out) > MAX_SPEAK_CHARS - len(sentence)


def test_caps_at_a_word_when_no_sentence_ends() -> None:
    out = speakable("word " * 300)
    assert len(out) <= MAX_SPEAK_CHARS
    assert out.endswith("…") and not out[:-1].endswith(" ")
    assert "wor…" not in out  # never cut inside a word


def test_cap_never_ends_on_a_decimal_point() -> None:
    text = "x" * 595 + " 3.14159 and more"
    out = speakable(text)
    assert len(out) <= MAX_SPEAK_CHARS and not out.endswith("3.")


def test_custom_cap() -> None:
    assert speakable("One. Two. Three.", max_chars=9) == "One. Two."


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        # digit * digit is multiplication, not emphasis or a stray mark
        ("3*4 is 12.", "3 times 4 is 12."),
        ("2 * 3 = 6", "2 times 3 = 6"),
        ("Use `2*8` cores.", "Use 2 times 8 cores."),
        ("**5** items", "5 items"),
        # ~ before a number is "about"; strikethrough still works
        ("It takes ~5 minutes.", "It takes about 5 minutes."),
        ("Roughly ~ 20 people.", "Roughly about 20 people."),
        ("~~5~~ 6 seats", "5 6 seats"),
        # only real HTML tag names are stripped
        ("x <y and z> w", "x <y and z> w"),
        ("<em>really</em> good<br/>", "really good"),
        ('<span class="x">ok</span>', "ok"),
        # one level of parentheses inside a markdown link target
        ("See [Foo](https://en.wikipedia.org/wiki/Foo_(bar)) now.", "See Foo now."),
        ("![chart](https://x.io/a_(b).png) here", "chart here"),
    ],
)
def test_review_fixes_keep_meaning(raw: str, want: str) -> None:
    assert speakable(raw) == want


@pytest.mark.parametrize("raw", ["__", "_", "_ _", "___ __"])
def test_underscores_alone_are_nothing_to_say(raw: str) -> None:
    assert speakable(raw) == ""


def test_single_huge_word_is_hard_cut() -> None:
    out = speakable("a" * 1000)
    assert len(out) <= MAX_SPEAK_CHARS and out.startswith("aaa")
