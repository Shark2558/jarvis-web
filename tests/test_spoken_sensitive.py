# tests/test_spoken_sensitive.py -- the stricter filter for text read ALOUD (R1 D16 review fix).
from __future__ import annotations

import pytest

from jarvis.recall.sensitive import sensitive_reason, spoken_sensitive
from jarvis.tools.gmail_digest import withheld

LEAKS = [
    "Swiggy 482910 is your OTP for login",
    "Use 482910 to sign in to Swiggy",
    "Your balance is Rs 1,23,456.78 Bank",
    "Rs 500 spent on card at Amazon",
    "Rs 5,000 debited from your account",
    "Rs 5,000 credited to a/c XX1234",
    "Your account ending 4321 statement is ready",
    "Your txn of Rs 250 was successful",
    "Transaction alert: Rs 999",
    "Verify your email with code 123456",
    "Your PIN is 4821",
    "Your password reset code: 8841",
    "aapka OTP 482910 hai",
    "Aapka OTP hai 482910, kisi ko na batayein",
    "aapka verification code 4829",
    "aapke khate mein Rs 500 jama hue",
    "Rs 500 aapke account se debit hua",
    "Your OTP",
    "A/c XX1234 debited Rs 5,000 on 04-Nov",
]
HARMLESS = [
    "Lunch tomorrow? Priya Are you free at one",
    "Your parcel has shipped, arriving Monday",
    "Meeting moved to 1530 in room 4",
    "Happy birthday! See you on the 12th",
    "Your order 12345 is on the way",
]


@pytest.mark.parametrize("text", LEAKS)
def test_leaks_are_withheld_by_the_spoken_filter_and_the_digest(text: str) -> None:
    assert spoken_sensitive(text) is True
    assert withheld(text) is True


@pytest.mark.parametrize("text", HARMLESS)
def test_harmless_mail_is_read(text: str) -> None:
    assert spoken_sensitive(text) is False
    assert withheld(text) is False


def test_it_is_separate_from_the_write_path_filter() -> None:
    # the write path would not refuse these; the spoken one must (and not the other way round)
    assert sensitive_reason("Swiggy 482910 is your OTP for login") is None
    assert spoken_sensitive("Swiggy 482910 is your OTP for login")


@pytest.mark.parametrize("text", ["", "   ", "\u200b"])
def test_empty_text_is_not_sensitive(text: str) -> None:
    assert spoken_sensitive(text) is False


def test_look_alike_letters_and_zero_width_characters_do_not_hide_it() -> None:
    assert spoken_sensitive("Swiggy 482910 is your O\u200bTP")
    assert spoken_sensitive("Rs 500 d\u200bebited")
    assert spoken_sensitive("Use 482910 to sіgn in")  # Cyrillic i


def test_a_huge_input_is_cheap() -> None:
    import time

    start = time.perf_counter()
    assert spoken_sensitive("x " * 200_000) is False
    assert time.perf_counter() - start < 0.5
