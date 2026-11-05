# tests/test_spoken_split_digits.py -- review slice 3 item 2/3: digits split by joiners, spelled-out
# numbers, amounts in words, street addresses and bare domains must not reach a speaker.
from __future__ import annotations

import re
import time

import pytest

from jarvis.recall.sensitive import join_digits, spoken_sensitive
from jarvis.tools.spoken import mask_for_speech

SPLIT_CODES = [
    "Your verification code 123 - 456",
    "Login PIN 1 - 2 - 3 - 4",
    "Your code is 123 \u00b7 456 for Swiggy",
    "Your OTP 12|34|56",
    "Your OTP 123\u2013456",
    "Your OTP 123*456",
    "OTP 1_2_3_4",
    "Your OTP is 12 * 34",
    "Your password is 12 / 34",
    "CVV 1 2 3 4",
]


@pytest.mark.parametrize("text", SPLIT_CODES)
def test_split_digits_beside_a_secret_word_are_withheld(text: str) -> None:
    assert spoken_sensitive(text), text


@pytest.mark.parametrize("text", SPLIT_CODES)
def test_split_digits_never_survive_masking(text: str) -> None:
    out = mask_for_speech(text)
    assert len(re.sub(r"\D", "", out)) < 4, out


def test_join_digits_closes_one_to_three_non_alphanumeric_characters() -> None:
    assert join_digits("12|34") == "1234"
    assert join_digits("1 - 2") == "12"
    assert join_digits("1--2") == "12"
    assert join_digits("1 ---- 2") == "1 ---- 2"  # four characters are not a joiner
    assert join_digits("1a2") == "1a2"


def test_clock_times_and_short_numbers_stay_readable() -> None:
    text = "Meeting at 10:30 on 5 Nov in room 4"
    assert mask_for_speech(text) == text
    assert not spoken_sensitive(text)
    assert mask_for_speech("10:30, 11:45") == "10:30, 11:45"


SPELLED = [
    "Your OTP is one two three four five six",
    "code: nine four one seven",
    "Your OTP is ek do teen char paanch chhe",
    "OTP onnu randu moonnu naalu anchu aaru",
    "one-two-three-four",
]


@pytest.mark.parametrize("text", SPELLED)
def test_runs_of_digit_words_are_masked(text: str) -> None:
    out = mask_for_speech(text)
    assert not re.search(
        r"\b(?:one|two|three|four|five|six|seven|eight|nine|ek|do|teen|char|paanch|chhe|"
        r"onnu|randu|moonnu|naalu|anchu|aaru)\b",
        out,
        re.I,
    ), out
    assert "a number" in out


@pytest.mark.parametrize("text", SPELLED[:4])
def test_spelled_codes_beside_a_secret_word_are_withheld(text: str) -> None:
    assert spoken_sensitive(text), text


def test_two_digit_words_alone_are_ordinary_words() -> None:
    assert mask_for_speech("Free at one or two") == "Free at one or two"
    assert mask_for_speech("do it now") == "do it now"


@pytest.mark.parametrize(
    "text",
    [
        "Pay five thousand rupees",
        "Pay rupees five thousand",
        "Send two lakh now",
        "Rs fifty",
        "twenty five crore INR",
        "paanch hazaar rupees",
    ],
)
def test_number_words_next_to_a_currency_word_become_an_amount(text: str) -> None:
    out = mask_for_speech(text)
    assert "an amount" in out
    assert not re.search(r"thousand|fifty|twenty|five|two|hazaar|lakh|crore|rupees", out, re.I), out


def test_amount_in_words_keeps_the_rest_of_the_sentence() -> None:
    assert mask_for_speech("Pay five thousand rupees today") == "Pay an amount today"


@pytest.mark.parametrize(
    "text",
    [
        "Flat 12, Green Park Road",
        "House no 4 Gandhi Nagar",
        "plot 7 MG Marg",
        "Door 3, 5th Cross, HSR Layout",
        "Meet at No. 42 Main Road",
    ],
)
def test_street_addresses_are_masked(text: str) -> None:
    out = mask_for_speech(text)
    assert "a link" in out
    assert not re.search(r"green park|gandhi|marg|hsr|main road|\b42\b", out, re.I), out


@pytest.mark.parametrize("text", ["see evil.com now", "go to pay.example.in", "bank-login.co.in"])
def test_bare_domains_are_masked(text: str) -> None:
    out = mask_for_speech(text)
    assert "a link" in out
    assert not re.search(r"\.com|\.in\b", out), out


def test_ordinary_dotted_text_is_not_a_domain() -> None:
    text = "e.g. the report, i.e. Mr. Rao said ok."
    assert mask_for_speech(text) == text


def test_the_new_masks_are_cheap_on_hostile_input() -> None:
    for hostile in (
        "one " * 5_000,
        "five thousand " * 1_500,
        "flat 1 " * 3_000,
        "a." * 10_000,
        "1 - " * 5_000,
        "12|" * 6_000,
    ):
        start = time.perf_counter()
        mask_for_speech(hostile)
        spoken_sensitive(hostile)
        assert time.perf_counter() - start < 0.5, hostile[:12]
