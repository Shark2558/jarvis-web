# tests/test_vitals_status.py -- R4 D3: ok -> amber -> red from usage and expiry; the record model.
from __future__ import annotations

import pytest
from pydantic import ValidationError
from vitals_fakes import T0, key

from jarvis.vitals.models import Provider
from jarvis.vitals.status import status_of

AMBER = 0.8
DAYS = 30


def st(p: Provider) -> str:
    return status_of(p, T0, AMBER, DAYS).status


def test_ok_when_well_under_the_limit() -> None:
    assert st(key(limit=100, used=79)) == "ok"


def test_amber_at_the_amber_fraction_exactly() -> None:
    assert st(key(limit=100, used=80)) == "amber"


def test_red_at_the_limit() -> None:
    assert st(key(limit=100, used=100)) == "red"


def test_red_when_over_the_limit() -> None:
    assert st(key(limit=100, used=250)) == "red"


def test_amber_when_expiring_within_the_window() -> None:
    assert st(key(expires_in_days=30)) == "amber"


def test_ok_when_expiry_is_beyond_the_window() -> None:
    assert st(key(expires_in_days=31)) == "ok"


def test_red_when_expired() -> None:
    assert st(key(expires_in_days=-1)) == "red"


def test_red_at_the_exact_expiry_instant() -> None:
    assert st(key(expires_in_days=0)) == "red"


def test_worst_of_usage_and_expiry_wins() -> None:
    assert st(key(limit=100, used=10, expires_in_days=-2)) == "red"
    assert st(key(limit=100, used=90, expires_in_days=400)) == "amber"


def test_no_limit_and_no_expiry_is_ok() -> None:
    assert st(key()) == "ok"


def test_zero_limit_does_not_divide_by_zero() -> None:
    assert st(key(limit=0, used=0)) == "ok"


def test_auto_record_with_unreadable_usage_is_unknown() -> None:
    assert st(key(source="auto", kind="quota", limit=100, used=None)) == "unknown"


def test_manual_record_without_usage_is_judged_by_expiry_only() -> None:
    assert st(key(limit=100, used=None, expires_in_days=5)) == "amber"


def test_percent_is_reported_against_the_limit() -> None:
    assert status_of(key(limit=200, used=50), T0, AMBER, DAYS).percent == 25.0
    assert status_of(key(), T0, AMBER, DAYS).percent is None


def test_reason_uses_fixed_words_and_no_dollar_sign() -> None:
    r = status_of(key(limit=100, used=90), T0, AMBER, DAYS).reason
    assert "90%" in r and "$" not in r
    assert "expired" in status_of(key(expires_in_days=-1), T0, AMBER, DAYS).reason


@pytest.mark.parametrize(
    "bad",
    [
        {"id": "Bad Id"},
        {"id": ""},
        {"limit": -1},
        {"limit": float("inf")},
        {"used": float("nan")},
        {"kind": "wallet"},
        {"label": ""},
        {"extra": 1},
    ],
)
def test_record_rejects_invalid_input(bad: dict) -> None:
    base = {"id": "brave", "label": "Brave", "kind": "key"}
    with pytest.raises(ValidationError):
        Provider(**{**base, **bad})


def test_record_collapses_whitespace_in_text() -> None:
    p = Provider(id="x", label="  My   key ", kind="key", note="a\n b")
    assert p.label == "My key" and p.note == "a b"
