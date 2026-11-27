"""R18 A2: the in-call reply guard (docs/plans/r18-calls.md 4.6, 8; BUILD-BRIEF row A2 item 4).

Everything JARVIS is about to say in a call passes `check_reply` first: no OTP-, card-, bank-,
Aadhaar- or PAN-shaped strings unless that exact value is on the card, no agreeing to payments,
nothing outside the card's allowances.
"""

from __future__ import annotations

import pytest

from jarvis.calls.guard import (
    GuardContext,
    card_values,
    check_dtmf,
    check_reply,
    digit_runs,
    heard_values,
)

CARD = card_values(
    [
        "Book a laundry pickup",
        "Name to give: Asha. Number to give: +91 90000 00001",
        "Acceptable: 2026-11-28 10:00-12:00",
    ]
)
CTX = GuardContext(card=CARD, heard=frozenset(), first_name="Asha")


def test_digit_runs_join_spaced_and_hyphenated_groups() -> None:
    assert digit_runs("call 98765 43210 now") == ["9876543210"]
    assert digit_runs("1234-5678-9012-3456") == ["1234567890123456"]
    assert digit_runs("at 10:30 on 28/11") == ["10", "30", "28", "11"]


def test_digit_runs_read_other_scripts_and_number_words() -> None:
    assert digit_runs("OTP ४८२९१३") == ["482913"]  # Devanagari digits
    assert digit_runs("four eight two nine one three") == ["482913"]
    assert digit_runs("double nine eight seven") == ["9987"]
    assert digit_runs("चार आठ दो नौ") == ["4829"]
    assert digit_runs("ek do teen char") == ["1234"]
    assert digit_runs("forty-eight twenty-nine") == ["4829"]


def test_short_numbers_pass() -> None:
    assert check_reply("Two shirts and 3 trousers, pickup at 10:30.", "", CTX).ok


@pytest.mark.parametrize(
    ("say", "reason"),
    [
        ("The OTP is 482913.", "digits"),
        ("It is four eight two nine one three.", "digits"),
        ("My card is 4111 1111 1111 1111.", "digits"),
        ("Aadhaar 2345 6789 0123.", "digits"),
        ("Account 123456789012.", "digits"),
        ("His PAN is ABCDE1234F.", "pan"),
        ("The IFSC is SBIN0001234.", "ifsc"),
        ("Send it to asha@okaxis.", "handle"),
        ("Visit https://example.test/pay now.", "link"),
    ],
)
def test_secret_shaped_strings_are_refused(say: str, reason: str) -> None:
    verdict = check_reply(say, "", CTX)
    assert not verdict.ok
    assert reason in verdict.reasons


def test_values_on_the_card_may_be_said() -> None:
    assert check_reply("You can reach Asha on 90000 00001.", "", CTX).ok
    assert check_reply("Saturday 28 November 2026 at 10:00.", "", CTX).ok


def test_a_number_not_on_the_card_is_refused_even_when_close() -> None:
    assert not check_reply("Reach her on 90000 00002.", "", CTX).ok


def test_short_numbers_the_other_person_said_may_be_repeated_back() -> None:
    heard = heard_values(["My booking number is 45 678 and call back on 90000 00009"])
    ctx = GuardContext(card=CARD, heard=heard, first_name="Asha")
    assert check_reply("Booking number 45678, noted.", "", ctx).ok
    assert check_reply("I will give Asha the number 9000000009.", "", ctx).ok


def test_long_numbers_heard_are_never_repeated() -> None:
    heard = heard_values(["My Aadhaar is 2345 6789 0123"])
    ctx = GuardContext(card=CARD, heard=heard, first_name="Asha")
    assert not check_reply("Your Aadhaar 234567890123 is noted.", "", ctx).ok


def test_the_english_rendering_is_checked_too() -> None:
    verdict = check_reply("ഒടിപി പറയാം", "The OTP is 482913.", CTX)
    assert not verdict.ok


@pytest.mark.parametrize(
    "english",
    [
        "Sure, Asha will pay 500 in advance.",
        "Okay, we can transfer the deposit today.",
        "Yes, the advance payment is fine.",
        "I will send the money by UPI.",
    ],
)
def test_agreeing_to_pay_is_refused(english: str) -> None:
    verdict = check_reply(english, english, CTX)
    assert not verdict.ok
    assert "payment" in verdict.reasons


@pytest.mark.parametrize(
    "english",
    [
        "No payment will be made on this call.",
        "Asha will not pay in advance.",
        "I can't agree to any payment; I will check with Asha.",
    ],
)
def test_refusing_payment_is_fine(english: str) -> None:
    assert check_reply(english, english, CTX).ok


def test_payment_words_are_judged_per_sentence() -> None:
    text = "No problem. Asha will pay on delivery."
    assert not check_reply(text, text, CTX).ok


def test_empty_reply_is_refused() -> None:
    verdict = check_reply("   ", "", CTX)
    assert not verdict.ok
    assert "empty" in verdict.reasons


def test_dtmf_keys() -> None:
    assert check_dtmf("1", CTX).ok
    assert check_dtmf("*#", CTX).ok
    assert not check_dtmf("1a", CTX).ok
    assert not check_dtmf("", CTX).ok
    assert not check_dtmf("482913", CTX).ok
    assert check_dtmf("9000000001", CTX).ok  # on the card


def test_verdict_never_carries_the_text() -> None:
    verdict = check_reply("The OTP is 482913.", "", CTX)
    assert "482913" not in repr(verdict)
