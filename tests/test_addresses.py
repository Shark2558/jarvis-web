# tests/test_addresses.py — security review M4: strict recipients, header values, card text
from __future__ import annotations

import pytest

from jarvis.tools.addresses import display_address, parse_address, parse_recipients
from jarvis.tools.card import one_line
from jarvis.tools.gmail_mime import check_header_value

# ---- recipients -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "good, expected",
    [
        ("priya@example.com", "priya@example.com"),
        ("  Priya.S+work@Example.COM ", "priya.s+work@example.com"),
        ("o'brien@example.co.uk", "o'brien@example.co.uk"),
        ("user@bücher.example", "user@xn--bcher-kva.example"),  # stored as IDNA (ASCII headers)
        ("user@xn--bcher-kva.example", "user@xn--bcher-kva.example"),
    ],
)
def test_parse_address_accepts_plain_addr_specs(good: str, expected: str) -> None:
    assert parse_address(good) == expected


@pytest.mark.parametrize(
    "bad",
    [
        'a@b.c"x',  # quote after the domain
        '"a"@b.co',  # quoted local part
        "a(b)@c.co",  # comment
        "a@b..co",  # empty label
        "a..b@c.co",  # consecutive dots in the local part
        ".a@c.co",  # leading dot
        "a.@c.co",  # trailing dot
        "a@.c.co",
        "a@c.co.",
        "a@c",  # single-label domain
        "a@-c.co",  # label starts with a hyphen
        "a@[1.2.3.4]",  # domain literal
        "Name <a@c.co>",  # display names are not recipients
        "a@b@c.co",
        "a b@c.co",
        "a@c.co\u2028bcc@evil.example",  # line separator
        "a@c.co\u0085",  # NEL (C1)
        "a@c\u202e.co",  # bidi override
        "ä@c.co",  # non-ASCII local part
        "a@c.123",  # numeric TLD
        "",
    ],
)
def test_parse_address_rejects_anything_but_a_bare_addr_spec(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_address(bad)


def test_parse_recipients_splits_lists_and_rejects_quote_spanning_input() -> None:
    assert parse_recipients("a@x.co, b@y.co") == ["a@x.co", "b@y.co"]
    assert parse_recipients(["a@x.co", "B@Y.co"]) == ["a@x.co", "b@y.co"]
    assert parse_recipients("a@x.co, a@x.co") == ["a@x.co"]  # one mail per address
    with pytest.raises(ValueError, match="recipient"):
        parse_recipients('"a@x.co, b"@y.co')  # one quoted local part, not two addresses
    with pytest.raises(ValueError, match="at least one"):
        parse_recipients(" , ")
    with pytest.raises(ValueError):
        parse_recipients(["ok@x.co", "evil@x..co"])


def test_display_address_shows_unicode_and_punycode_side_by_side() -> None:
    assert display_address("priya@example.com") == "priya@example.com"
    shown = display_address(parse_address("billing@p\u0430ypal.com"))  # Cyrillic \u0430
    assert "p\u0430ypal.com" in shown and "xn--pypal-4ve.com" in shown


# ---- header values --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    ["s\nBcc: x@y.z", "s\r", "tab\there", "nul\x00", "nel\x85", "ls\u2028x", "ps\u2029x", "\x7f"],
)
def test_header_values_reject_c0_c1_and_line_separators(bad: str) -> None:
    with pytest.raises(ValueError):
        check_header_value(bad, name="subject")


def test_header_values_accept_ordinary_unicode() -> None:
    assert check_header_value("Q4 — numbers ✓", name="subject") == "Q4 — numbers ✓"


# ---- card text ------------------------------------------------------------------------------


def test_one_line_strips_controls_bidi_and_collapses_whitespace() -> None:
    hostile = "Invoice\u202egpj.exe\r\nBcc:\tx\u2028y\u200b\u2066z\u2069  end\x07"
    out = one_line(hostile, 200)
    assert out == "Invoicegpj.exe Bcc: x yz end"  # invisible chars go, breaks become spaces
    for ch in ("\u202e", "\r", "\n", "\t", "\u2028", "\u200b", "\u2066", "\x07"):
        assert ch not in out


def test_one_line_truncates_with_an_ellipsis() -> None:
    assert one_line("abcdef", 4) == "abc…"
    assert one_line("abc", 4) == "abc"
    assert one_line(None, 4) == ""
