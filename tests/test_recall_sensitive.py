# tests/test_recall_sensitive.py — slice 8 D9: the deterministic sensitive-data filter (every
# write path runs it) and the special-category check learned facts also pass.
from __future__ import annotations

import pytest

from jarvis.recall.sensitive import is_sensitive, sensitive_reason, special_category

SENSITIVE = [
    "My card is 4111 1111 1111 1111",  # Visa test number, Luhn-valid
    "card 5500-0000-0000-0004 expires soon",
    "Aadhaar 2345 6789 0123",
    "my aadhar number is 234567890123",
    "PAN ABCDE1234F",
    "pan is abcde1234f",
    "IFSC HDFC0001234 for the salary account",
    "my ifsc code is sbin0004567",
    "IBAN DE89 3704 0044 0532 0130 00",
    "Account number 123456789012 at SBI",
    "my a/c no 50100123456789",
    "The wifi password is hunter2",
    "password: Tr0ub4dor&3",
    "My PIN is 4521",
    "ATM pin 9911",
    "UPI PIN 123456",
    "OTP 482913",
    "the one-time password is 112233",
    "CVV 123",
    "passport number K1234567",
    "my api key is sk-abcdefghijklmnopqrstuv",
    "AKIAABCDEFGHIJKLMNOP is the aws key",
]

FINE = [
    "Owner prefers window seats on flights",
    "Daughter Anaya studies in class 3",
    "Lives in Thiruvananthapuram",
    "Uses a password manager for everything",
    "The PIN code of the office is 695581",  # an Indian postal code, not a secret
    "pincode 682001",
    "Leads a team of 30 people",
    "Phone number is +91 98765 43210",
    "Prefers meetings after 10:00",
    "Born in 1988",
    "Flight AI 512 on 12 Dec",
    "Budget for the trip is 150000 rupees",
    "Card games on Friday with friends",
]


@pytest.mark.parametrize("text", SENSITIVE)
def test_sensitive_statements_are_caught(text: str) -> None:
    assert is_sensitive(text), text
    assert sensitive_reason(text)


@pytest.mark.parametrize("text", FINE)
def test_ordinary_facts_pass(text: str) -> None:
    assert not is_sensitive(text), (text, sensitive_reason(text))


def test_luhn_matters_for_bare_card_like_numbers() -> None:
    assert is_sensitive("4111111111111111")
    assert not is_sensitive("Order 4111111111111112 shipped")  # fails Luhn, not a card


def test_reason_never_echoes_the_value() -> None:
    reason = sensitive_reason("My card is 4111 1111 1111 1111") or ""
    assert "4111" not in reason


@pytest.mark.parametrize(
    "text",
    [
        "Was diagnosed with diabetes last year",
        "Takes medication for blood pressure",
        "Is a practising Hindu",
        "Belongs to a particular caste",
        "Votes for a political party",
        "Is gay",
    ],
)
def test_special_categories_are_flagged(text: str) -> None:
    assert special_category(text)


@pytest.mark.parametrize("text", ["Prefers tea to coffee", "Works at Amnex", "Visits Goa often"])
def test_special_categories_leave_ordinary_facts(text: str) -> None:
    assert not special_category(text)


@pytest.mark.parametrize(
    "text",
    [
        "Salary a/c no\n50100123456789",  # a line break is a separator, not nothing
        "My card\t4111 1111 1111 1111",
        "card 4111.1111.1111.1111",
        "card 4111​1111​1111​1111",  # zero-width spaces
        "card ４１１１ １１１１ １１１１ １１１１",  # fullwidth digits
        "Aadhaar 2345.6789.0123",
    ],
)
def test_separators_and_disguises_do_not_hide_a_number(text: str) -> None:
    assert is_sensitive(text), text


# ---- review findings: bypasses (finding 7) ---------------------------------------------------

BYPASSES = [
    "card 4111/1111/1111/1111",
    "card 4111,1111,1111,1111",
    "card 4111_1111_1111_1111",
    "card 4111–1111–1111–1111",  # en dash
    "card 4111 - 1111 - 1111 - 1111",
    "card 4111́ 1111 1111 1111",  # a combining mark
    "card 4111️ 1111 1111 1111",  # variation selector 16
    "card 4111‍1111⁠1111​1111",  # ZWJ, word joiner, ZWSP
    "Aadhaar 2345-6789 0123",
    "my uid 2345 67890123",
    "2345/6789/0123",
    "PAN ABCDE 1234 F",
    "PAN АBCDE1234F",  # Cyrillic А
    "PAN ΑΒCDE1234F",  # Greek Α Β
    "pan is abcde 1234 f",
    "IFSC НDFC0001234",  # Cyrillic Н
    "my passwords are hunter2",
    "the password for netflix is hunter2",
    "password for the bank site is Sup3rS3cret",
    "pw is hunter2",
    "pass: Sup3rS3cret",
    "my pаssword is hunter2",  # Cyrillic а
    "my pássword is hunter2",  # a combining accent
    "pin for my card is 4321",
    "ac no 50100123456780",
    "acc no. 50100123456780",
    "savings 50100123456780",
]

STILL_FINE = [
    "Boarding pass is in the blue bag",
    "Pin the report to the top of the channel",
    "Visited Paris 2019 a lot",
    "Meeting on 2026-11-15 at 10:30",
    "Passwords are kept in Bitwarden",
    "The wifi password is on the fridge",
    "Lives in തിരുവനന്തപുരം",
    "The AC in the bedroom is noisy",
]


@pytest.mark.parametrize("text", BYPASSES)
def test_disguised_numbers_and_phrasings_are_caught(text: str) -> None:
    assert is_sensitive(text), text


@pytest.mark.parametrize("text", STILL_FINE)
def test_the_wider_filter_still_lets_ordinary_facts_through(text: str) -> None:
    assert not is_sensitive(text), (text, sensitive_reason(text))
