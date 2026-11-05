# tests/test_vitals_guard.py -- R4 A fixes D-A1/D-A3/D-A4: the model-level secret guard, label rules
# and timezone-safe dates hold on every entry path.
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from jarvis.vitals.models import Provider
from jarvis.vitals.status import status_of

MIXED = "Ab3dE6gH9jK2mN5pQ8sT1vX4"  # 24 chars, upper + lower + digit


def make(**kw: object) -> Provider:
    base: dict[str, object] = {"id": "k", "label": "Key", "kind": "key"}
    return Provider(**{**base, **kw})  # type: ignore[arg-type]


def refused(**kw: object) -> str:
    with pytest.raises(ValidationError) as ei:
        make(**kw)
    return str(ei.value)


@pytest.mark.parametrize("field", ["note", "label"])
def test_a_secret_in_a_text_field_is_refused(field: str) -> None:
    assert "never paste" in refused(**{field: "x " + "sk-" + "A1b2C3d4" * 5}).lower()


def test_a_secret_in_the_unit_field_is_refused() -> None:
    assert "never paste" in refused(unit="sk-a1b2c3d4e5f6g7h8").lower()


def test_a_secret_in_the_id_field_is_refused() -> None:
    assert "never paste" in refused(id="a1b2c3d4" * 4).lower()


@pytest.mark.parametrize("sep", ["/", "+", ".", ":", "-", "_"])
def test_separator_broken_secrets_are_refused(sep: str) -> None:
    broken = sep.join([MIXED[:8], MIXED[8:16], MIXED[16:]])
    assert "never paste" in refused(note=broken).lower()


def test_error_text_never_contains_the_value() -> None:
    secret = "sk-" + "A1b2C3d4" * 5
    assert secret not in refused(note=secret)


def test_31_alnum_chars_are_allowed_but_32_are_refused() -> None:
    assert make(note="a" * 31).note == "a" * 31
    assert "never paste" in refused(note="a" * 32).lower()


def test_a_20_char_mixed_class_run_is_refused() -> None:
    assert "never paste" in refused(note=MIXED[:20]).lower()
    assert make(note="Quota2026Plan").note  # short mixed words are fine


@pytest.mark.parametrize(
    "value",
    [
        "sk-ant-api03-abcdef12",
        "AKIAABCDEFGH1234",
        "AIzaSyABCDEFGH123",
        "ghp_abcdefgh1234",
        "gho_abcdefgh1234",
        "github_pat_abcdefgh",
        "xoxb-12345678-abcd",
        "xoxa-12345678-abcd",
        "xoxp-12345678-abcd",
        "eyJhbGciOiJIUzI1",
        "tvly-abcdefgh1234",
        "12345678901:" + "A" * 5 + "b" * 25,
    ],
)
def test_known_key_prefixes_are_refused(value: str) -> None:
    assert "never paste" in refused(note=f"here {value}").lower()


def test_words_that_merely_contain_a_prefix_are_fine() -> None:
    assert make(note="risk-free task-list sk").note


def test_a_secret_split_across_two_fields_is_refused() -> None:
    assert "never paste" in refused(label="Key " + MIXED[:12], note=MIXED[12:] + "x9").lower()
    assert "never paste" in refused(id="a1b2c3d4e5f6a7b8", note="c9d0e1f2a3b4c5d6e7f8").lower()


def test_ordinary_long_text_is_not_a_false_positive() -> None:
    note = "Renews every January; billed to the shared card; ask finance before changing it"
    assert make(note=note, label="Brave Search API monthly quota plan").note == note


def test_auto_records_skip_the_guard() -> None:
    p = make(source="auto", id="quota_" + "a" * 30, label="Google Maps: Geocoding requests")
    assert p.source == "auto"


@pytest.mark.parametrize(
    "label",
    ["Bad: label", "mail@me", "see http://x", "www.evil", "evil.com now", "a" * 81, "x‮y"],
)
def test_labels_are_constrained_text(label: str) -> None:
    with pytest.raises(ValidationError):
        make(label=label)


def test_a_plain_label_with_allowed_punctuation_passes() -> None:
    assert make(label="Brave (search) & maps/geo - v2.5").label.startswith("Brave")


def test_date_only_expiry_is_end_of_that_day_in_the_owner_zone() -> None:
    p = make(expires_at="2026-11-05")

    assert p.expires_at is not None and p.expires_at.utcoffset() is not None
    assert p.expires_at.isoformat().startswith("2026-11-05T23:59:59")
    assert p.expires_at.isoformat().endswith("+05:30")


def test_naive_datetime_is_end_of_day_and_aware_is_kept() -> None:
    naive = make(reset_at=datetime(2026, 11, 5, 8, 0))
    aware = make(reset_at=datetime(2026, 11, 5, 8, 0, tzinfo=UTC))

    assert naive.reset_at is not None and naive.reset_at.hour == 23
    assert aware.reset_at == datetime(2026, 11, 5, 8, 0, tzinfo=UTC)


def test_an_ist_expiry_is_not_red_at_0530_ist() -> None:
    p = make(expires_at="2026-11-05")
    at_0530_ist = datetime(2026, 11, 5, 0, 0, tzinfo=UTC)  # 05:30 IST

    assert status_of(p, at_0530_ist, 0.8, 0).status == "ok"
    assert status_of(p, datetime(2026, 11, 5, 18, 30, tzinfo=UTC), 0.8, 0).status == "red"


def test_status_of_never_raises_on_a_naive_value() -> None:
    p = Provider.model_construct(
        id="k",
        label="K",
        kind="key",
        source="manual",
        limit=None,
        used=None,
        unit="",
        reset_at=None,
        expires_at=datetime(2026, 11, 5),
        note="",
    )

    now = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
    assert status_of(p, now, 0.8, 14).status in {"ok", "amber", "red"}
