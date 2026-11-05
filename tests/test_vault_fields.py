# tests/test_vault_fields.py -- R2 D4: deterministic date and last-4 extraction, day-first only
from __future__ import annotations

import datetime as dt

import pytest
from vault_fakes import pdf_with_text

from jarvis.documents.extract import extract
from jarvis.vault.fields import propose, verhoeff_ok

D = dt.date


def test_passport_dates_on_the_same_line() -> None:
    p = propose("Date of Issue: 12/02/2021\nDate of Expiry: 11/02/2031\nP1234567", "passport")
    assert p.expires_on == D(2031, 2, 11) and p.expires_label == "Date of Expiry"
    assert p.issued_on == D(2021, 2, 12) and p.last4 == "4567"


def test_value_on_the_next_line() -> None:
    p = propose("Valid Till\n14-03-2034\nDriving Licence", "driving_licence")
    assert p.expires_on == D(2034, 3, 14) and p.expires_label == "Valid Till"


def test_value_more_than_80_characters_away_is_not_taken() -> None:
    p = propose("Valid Till" + " " * 90 + "14/03/2034", "driving_licence")
    assert p.expires_on is None


@pytest.mark.parametrize(
    "written",
    ["14/03/2034", "14-03-2034", "14.03.2034", "14 Mar 2034", "14-Mar-2034", "2034-03-14"],
)
def test_all_indian_formats(written: str) -> None:
    assert propose(f"Valid Till: {written}", "driving_licence").expires_on == D(2034, 3, 14)


def test_day_first_never_month_first() -> None:
    assert propose("Valid upto: 03/12/2027", "puc").expires_on == D(2027, 12, 3)
    # 13 can only be a day: a month-first reading would be impossible, so it stays day-first
    assert propose("Valid upto: 13/01/2027", "puc").expires_on == D(2027, 1, 13)


@pytest.mark.parametrize("bad", ["12/03/27", "31/02/2027", "00/01/2027", "12/13/2027"])
def test_two_digit_year_or_impossible_date_gives_nothing(bad: str) -> None:
    assert propose(f"Valid upto: {bad}", "puc").expires_on is None


def test_two_different_candidates_give_nothing() -> None:
    assert (
        propose(
            "Policy Expiry 01/01/2027\nPolicy Expiry 01/02/2027", "vehicle_insurance"
        ).expires_on
        is None
    )


def test_the_same_date_twice_is_one_candidate() -> None:
    p = propose("Policy Expiry 01/01/2027\nPolicy Expiry: 01-01-2027", "vehicle_insurance")
    assert p.expires_on == D(2027, 1, 1)


def test_period_of_insurance_gives_both_dates() -> None:
    p = propose("Period of Insurance: 02/01/2026 to 01/01/2027", "vehicle_insurance")
    assert p.issued_on == D(2026, 1, 2) and p.expires_on == D(2027, 1, 1)


def test_registration_validity_beats_fitness() -> None:
    p = propose("Fitness Upto: 01/01/2030\nRegistration Validity: 05/05/2035", "vehicle_rc")
    assert p.expires_on == D(2035, 5, 5)
    only = propose("Fitness Upto: 01/01/2030", "vehicle_rc")
    assert only.expires_on == D(2030, 1, 1)


def test_a_label_without_a_value_does_not_borrow_the_next_labels_date() -> None:
    p = propose("Valid Till:\nDate of Issue: 01/01/2020", "driving_licence")
    assert p.expires_on is None and p.issued_on == D(2020, 1, 1)


def test_types_that_do_not_expire_read_no_expiry_label_requirement() -> None:
    assert propose("Permanent Account Number\nABCDE1234F", None).last4 == "234F"


def test_last4_patterns() -> None:
    assert propose("ABCDE1234F", "pan").last4 == "234F"
    assert propose("K1234567", "passport").last4 == "4567"
    assert propose("KL07 2015000123", "driving_licence").last4 is None  # 13 digits needed
    assert propose("KL-07-2015-0001234", "driving_licence").last4 == "1234"
    assert propose("KL 07 AB 4821", "vehicle_rc").last4 == "4821"
    assert propose("Policy no 99887766", "vehicle_insurance").last4 is None  # never proposed


def test_last4_only_when_one_candidate() -> None:
    assert propose("ABCDE1234F and FGHIJ5678K", "pan").last4 is None


def test_aadhaar_needs_a_valid_verhoeff_check() -> None:
    good = "2363 1234 5678"
    # build a valid number: find a final digit that satisfies the check
    base = "23631234567"
    num = next(base + str(d) for d in range(10) if verhoeff_ok(base + str(d)))
    spaced = f"{num[:4]} {num[4:8]} {num[8:]}"
    assert propose(spaced, "aadhaar").last4 == num[-4:]
    bad = base + str((int(num[-1]) + 1) % 10)
    assert propose(f"{bad[:4]} {bad[4:8]} {bad[8:]}", "aadhaar").last4 is None
    assert good


def test_type_guess_from_fixed_phrases() -> None:
    assert propose("Driving Licence\nValid Till 14/03/2034").type == "driving_licence"
    assert propose("Certificate of Registration").type == "vehicle_rc"
    assert propose("INCOME TAX DEPARTMENT Permanent Account Number Card").type == "pan"
    assert propose("Pollution Under Control Certificate").type == "puc"
    assert propose("nothing recognisable here").type is None
    assert propose("Driving Licence", "passport").type is None  # the owner's choice wins


def test_empty_and_odd_input() -> None:
    assert propose("", None).empty
    assert propose("\x00\x01 weird �", "passport").empty


def test_proposal_never_carries_raw_text() -> None:
    p = propose("Date of Expiry: 11/02/2031 secret words here", "passport")
    assert "secret" not in p.model_dump_json()


def test_helper_pdf_goes_through_the_real_extractor() -> None:
    pdf = pdf_with_text(["Driving Licence", "Valid Till: 14-03-2034", "KL-07-2015-0001234"])
    text = extract(pdf, "pdf").text
    p = propose(text, None)
    assert p.type == "driving_licence" and p.expires_on == D(2034, 3, 14) and p.last4 == "1234"
