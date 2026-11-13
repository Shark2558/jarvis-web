# tests/test_r7_d_watch_intake.py -- R7 Part D (docs/plans/r7-mobile.md D17; phone-contract.md
# section 4 `health`): what the phone's `health` door may hand the server. A body outside the
# contract is refused whole, in fixed words that never echo a value: an unknown key, a number out
# of range (steps, heart rate, stage minutes), a float where an integer belongs, a day outside the
# last 35, more than 35 days, a session that ends before it starts or lasts more than a day.
from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from jarvis.watch.models import (
    MAX_DAYS,
    IntakeRefused,
    parse_health,
    source_of,
)

TODAY = date(2026, 11, 13)


def _session(**over: Any) -> dict[str, Any]:
    s: dict[str, Any] = {
        "start": "2026-11-11T23:50:00+05:30",
        "end": "2026-11-12T06:30:00+05:30",
        "writer": "com.noisefit",
        "stages": {"awake": 12, "light": 210, "deep": 80, "rem": 98},
    }
    s.update(over)
    return s


def _day(**over: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "date": "2026-11-12",
        "steps": {"count": 8123, "writer": "com.noisefit"},
        "heart": {"min": 58, "avg": 74, "max": 131, "writer": "com.noisefit"},
        "sleep": [_session()],
    }
    d.update(over)
    return d


def _body(*days: dict[str, Any]) -> bytes:
    return json.dumps({"v": 1, "days": list(days) or [_day()]}).encode()


def test_the_contracts_own_example_is_accepted() -> None:
    vectors = json.loads(open("tests/fixtures/r7/phone_vectors.json", encoding="utf-8").read())
    case = next(c for c in vectors["cases"] if c["name"] == "health")
    got = parse_health(case["body"].encode(), TODAY)
    assert [d.date for d in got.days] == [date(2026, 11, 12), date(2026, 11, 13)]
    first = got.days[0]
    assert first.steps is not None and first.steps.count == 8123
    assert first.heart is not None and (first.heart.min, first.heart.max) == (58, 131)
    assert first.sleep[0].minutes == 400 and first.sleep[0].stages is not None
    assert got.days[1].heart is None and got.days[1].sleep == ()


@pytest.mark.parametrize(
    ("change", "why"),
    [
        ({"steps": {"count": -1, "writer": "com.noisefit"}}, "negative steps"),
        ({"steps": {"count": 200_001, "writer": "com.noisefit"}}, "too many steps"),
        ({"steps": {"count": 12.5, "writer": "com.noisefit"}}, "a float"),
        ({"steps": {"count": "8000", "writer": "com.noisefit"}}, "a string"),
        ({"steps": {"count": True, "writer": "com.noisefit"}}, "a bool"),
        ({"heart": {"min": 19, "avg": 70, "max": 120, "writer": "x.y"}}, "heart too low"),
        ({"heart": {"min": 50, "avg": 70, "max": 251, "writer": "x.y"}}, "heart too high"),
        ({"heart": {"min": 80, "avg": 70, "max": 120, "writer": "x.y"}}, "min above avg"),
        ({"heart": {"min": 50, "avg": 130, "max": 120, "writer": "x.y"}}, "avg above max"),
        ({"sleep": [_session(stages={"awake": -1, "light": 1, "deep": 1, "rem": 1})]}, "stage"),
        ({"sleep": [_session(stages={"awake": 1441, "light": 1, "deep": 1, "rem": 1})]}, "stage"),
        ({"sleep": [_session(stages={"awake": 300, "light": 300, "deep": 1, "rem": 1})]}, "sum"),
        ({"sleep": [_session(end="2026-11-11T23:00:00+05:30")]}, "ends before it starts"),
        ({"sleep": [_session(end="2026-11-13T06:30:00+05:30")]}, "longer than a day"),
        ({"sleep": [_session(start="2026-11-11T23:50:00")]}, "no offset"),
        ({"sleep": [_session(writer="com.noisefit; DROP")]}, "a writer that is no package"),
        ({"sleep": [_session(writer="a" * 200)]}, "a writer too long"),
        ({"sleep": [_session()] * 13}, "too many sessions"),
        ({"date": "2026-13-01"}, "no such date"),
        ({"surprise": 1}, "an unknown key"),
    ],
)
def test_a_value_outside_the_contract_refuses_the_whole_body(
    change: dict[str, Any], why: str
) -> None:
    with pytest.raises(IntakeRefused) as ei:
        parse_health(_body(_day(**change)), TODAY)
    words = str(ei.value)
    assert words == IntakeRefused.WORDS, why  # fixed words: no value is ever echoed
    assert not any(ch.isdigit() for ch in words)


@pytest.mark.parametrize(
    "when", ["2026-10-08", "2026-11-15", "2020-01-01"]
)  # 36 days back; two days ahead; long ago
def test_a_day_outside_the_last_35_is_refused(when: str) -> None:
    with pytest.raises(IntakeRefused):
        parse_health(_body(_day(date=when, sleep=[])), TODAY)


def test_the_window_holds_35_days_and_tomorrow_for_a_time_zone_ahead() -> None:
    oldest = date.fromordinal(TODAY.toordinal() - (MAX_DAYS - 1)).isoformat()
    got = parse_health(_body(_day(date=oldest, sleep=[]), _day(date="2026-11-14", sleep=[])), TODAY)
    assert len(got.days) == 2


def test_more_than_35_days_or_a_day_twice_is_refused() -> None:
    days = [
        _day(date=date.fromordinal(TODAY.toordinal() - i).isoformat(), sleep=[]) for i in range(36)
    ]
    with pytest.raises(IntakeRefused):
        parse_health(_body(*days), TODAY)
    with pytest.raises(IntakeRefused):
        parse_health(_body(_day(sleep=[]), _day(sleep=[])), TODAY)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"not json",
        b"[]",
        b'{"v":2,"days":[]}',
        b'{"v":1}',
        b'{"v":1,"days":[]}',
        b'{"v":true,"days":[{"date":"2026-11-12","sleep":[]}]}',
        b"\xff\xfe",
    ],
)
def test_a_body_that_is_not_the_contract_is_refused(raw: bytes) -> None:
    with pytest.raises(IntakeRefused):
        parse_health(raw, TODAY)


def test_no_sleep_and_no_stages_are_fine() -> None:
    got = parse_health(_body(_day(steps=None, heart=None, sleep=[_session(stages=None)])), TODAY)
    day = got.days[0]
    assert day.steps is None and day.heart is None and day.sleep[0].stages is None


def test_the_writer_names_the_source_watch_or_phone() -> None:
    assert source_of("com.noisefit") == "watch"
    assert source_of("android") == "phone"
    assert source_of("com.google.android.apps.fitness") == "phone"  # any other app: the phone
