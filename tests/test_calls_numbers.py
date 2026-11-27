# tests/test_calls_numbers.py — R18 A1: which numbers JARVIS may call (cards.check_number)
from __future__ import annotations

import pytest

from jarvis.calls.cards import NumberRefused, check_number, masked


@pytest.mark.parametrize(
    "raw",
    [
        "+91 90000 00001",
        "+919000000001",
        "90000 00001",
        "090000 00001",
        "919000000001",
        "0091 90000 00001",
        "(+91) 90000-00001",
        "+91 0 90000 00001",
    ],
)
def test_an_indian_mobile_in_any_usual_form_reads_as_e164(raw: str) -> None:
    assert check_number(raw) == "+919000000001"


def test_an_indian_landline_with_its_std_code_is_allowed() -> None:
    assert check_number("0471 255 0001") == "+914712550001"


def test_a_toll_free_1800_number_is_allowed() -> None:
    assert check_number("1800 123 4567") == "+9118001234567"
    assert check_number("+91 1800 123 4567") == "+9118001234567"


@pytest.mark.parametrize(
    "raw", ["100", "101", "102", "108", "112", "1091", "1098", "181", "+91 112", "0112", "1930"]
)
def test_emergency_numbers_are_refused(raw: str) -> None:
    with pytest.raises(NumberRefused) as err:
        check_number(raw)
    assert err.value.code == "emergency"
    assert "emergency" in str(err.value).lower()


@pytest.mark.parametrize("raw", ["1900 123 456", "+91 1900 1234 567", "19001234567"])
def test_premium_rate_numbers_are_refused(raw: str) -> None:
    with pytest.raises(NumberRefused) as err:
        check_number(raw)
    assert err.value.code == "premium"


@pytest.mark.parametrize("raw", ["+44 20 7946 0958", "001 415 555 2671", "+1 415 555 2671"])
def test_international_numbers_are_refused(raw: str) -> None:
    with pytest.raises(NumberRefused) as err:
        check_number(raw)
    assert err.value.code == "international"


@pytest.mark.parametrize("raw", ["121", "1909", "56767", "199", "14444", "1860 123 4567"])
def test_short_codes_and_special_services_are_refused(raw: str) -> None:
    with pytest.raises(NumberRefused) as err:
        check_number(raw)
    assert err.value.code == "short_code"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "abc",
        "+91 90000 0000",
        "+91 90000 000011",
        "9000０00001",
        "+91+9000000001",
        "1400 000 001",
        "+91 1400000001",
        None,
        9000000001,
    ],
)
def test_anything_else_is_not_a_number(raw: object) -> None:
    with pytest.raises(NumberRefused) as err:
        check_number(raw)
    assert err.value.code in {"invalid", "short_code"}


def test_masked_shows_only_the_country_code_and_last_four_digits() -> None:
    assert masked("+919000000001") == "+91 …0001"
    assert masked("not a number") == "…"
