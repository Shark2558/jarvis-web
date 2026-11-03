# tests/test_contacts_phones.py — slice 12 D5/D6: phone numbers as E.164 (+91 default for the
# owner's 10-digit Indian numbers) and the numbers written in the owner's own words. Pure.
from __future__ import annotations

import pytest

from jarvis.contacts.phones import (
    E164,
    india_assumed,
    is_e164,
    read_number,
    to_e164,
    typed_numbers,
    typed_with_country,
    wa_digits,
)


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("9876543210", "+919876543210"),  # 10-digit Indian mobile → +91
        ("98765 43210", "+919876543210"),
        ("98765-43210", "+919876543210"),
        ("(98765) 43210", "+919876543210"),
        ("09876543210", "+919876543210"),  # trunk 0
        ("919876543210", "+919876543210"),  # country code written without +
        ("+91 98765 43210", "+919876543210"),
        ("+91-98765-43210", "+919876543210"),
        ("+91 0 98765 43210", "+919876543210"),  # stray trunk 0 after +91
        ("0091 98765 43210", "+919876543210"),  # 00 international prefix
        ("4712345678", "+914712345678"),  # 10-digit landline (Thiruvananthapuram)
        ("+44 20 7946 0958", "+442079460958"),
        ("+1 (415) 555-0100", "+14155550100"),
        ("  +971 50 123 4567 ", "+971501234567"),
    ],
)
def test_numbers_become_e164(raw: str, want: str) -> None:
    assert to_e164(raw) == want
    assert is_e164(want) and E164.fullmatch(want)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "12345",  # too short
        "1234567890",  # 10 digits starting 1: not an Indian subscriber number
        "0123456789",
        "442079460958",  # foreign without + : ambiguous, refused
        "+0 123 456 7890",  # country codes never start with 0
        "+1234567890123456",  # 16 digits: longer than E.164
        "+91 98765 43210 ext 5",
        "98765 43210 or 99999 88888",
        "+91+98765",
        "98+765",
        "Ravi",
        "tel:+919876543210",
        "९८७६५४३२१०",  # Devanagari digits are refused (only ASCII digits are dialled)
        "+91 98765\u202e43210",  # a bidi override hidden inside
        None,
        42,
    ],
)
def test_anything_else_is_refused(raw: object) -> None:
    with pytest.raises(ValueError):
        to_e164(raw)  # type: ignore[arg-type]


def test_wa_digits_is_e164_without_the_plus() -> None:
    assert wa_digits("+919876543210") == "919876543210"
    with pytest.raises(ValueError):
        wa_digits("919876543210")


def test_typed_numbers_finds_what_the_owner_wrote_normalised() -> None:
    said = (
        "WhatsApp Ravi on 98765 43210 and tell +44 20 7946 0958 too. "
        "Not the date 2026-11-03, not 12:30, not order #123456."
    )
    assert typed_numbers(said) == frozenset({"+919876543210", "+442079460958"})


def test_typed_numbers_reads_two_numbers_side_by_side() -> None:
    assert typed_numbers("98765 43210 99999 88888") == frozenset({"+919876543210", "+919999988888"})
    assert typed_numbers("call 9876543210, or 0471 2345678.") == frozenset(
        {"+919876543210", "+914712345678"}
    )


def test_typed_numbers_is_bounded_and_ignores_junk() -> None:
    assert typed_numbers("") == frozenset()
    assert typed_numbers("no numbers here") == frozenset()
    long = " ".join(f"98765{i:05d}" for i in range(200))
    assert len(typed_numbers(long)) == 50  # at most MAX_TYPED read
    assert typed_numbers("9" * 10_000) == frozenset()  # one huge run: never a number


# ---- review S5: +91 numbers are exactly 10 digits; an assumed country is said so ----------------


@pytest.mark.parametrize(
    "raw",
    [
        "+91 98765 4321",  # 9 digits after +91: too short
        "+91 98765 432101",  # 11 digits after +91: too long
        "+91 12345 67890",  # an Indian number never starts with 0 or 1
        "0091 98765 4321",
    ],
)
def test_a_plus_91_number_must_have_ten_digits_after_it(raw: str) -> None:
    with pytest.raises(ValueError) as err:
        to_e164(raw)
    assert "check the number" in str(err.value) and "country code" in str(err.value)


@pytest.mark.parametrize(
    ("raw", "want", "assumed"),
    [
        ("9876543210", "+919876543210", True),
        ("09876543210", "+919876543210", True),
        ("07700900123", "+917700900123", True),  # a UK mobile written the UK way: read as Indian
        ("4155552671", "+914155552671", True),  # a US number without +1: read as Indian
        ("919876543210", "+919876543210", False),  # its country code is written
        ("+91 98765 43210", "+919876543210", False),
        ("0091 98765 43210", "+919876543210", False),
        ("+44 7700 900123", "+447700900123", False),
    ],
)
def test_read_number_says_when_india_was_assumed(raw: str, want: str, assumed: bool) -> None:
    assert read_number(raw) == (want, assumed)
    assert india_assumed(raw) is assumed


def test_india_assumed_is_false_for_anything_that_is_no_number() -> None:
    assert india_assumed("Ravi") is False and india_assumed(None) is False


def test_typed_with_country_keeps_only_numbers_written_with_their_code() -> None:
    said = "WhatsApp +91 98765 43210 or 99999 88888, or +44 20 7946 0958"
    assert typed_with_country(said) == frozenset({"+919876543210", "+442079460958"})
    assert typed_numbers(said) == frozenset({"+919876543210", "+919999988888", "+442079460958"})
