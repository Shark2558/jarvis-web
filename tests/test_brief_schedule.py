# tests/test_brief_schedule.py — slice 7: pure due-logic and settings validation
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from jarvis.brief.models import BriefRecord, BriefSettings, InboxState, parse_brief_time
from jarvis.brief.schedule import (
    CATCH_UP,
    STALE_CLAIM,
    claim_is_stale,
    due_at,
    in_delivery_window,
    is_due,
    local_date,
)

IST = ZoneInfo("Asia/Kolkata")
NY = ZoneInfo("America/New_York")


def _utc(s: str) -> datetime:
    return datetime.fromisoformat(s).astimezone(UTC)


def _record(status: str, claimed_at: datetime, **over: object) -> BriefRecord:
    base: dict[str, object] = {
        "user_id": "u_1",
        "date": "2027-01-15",
        "tz": "Asia/Kolkata",
        "status": status,
        "claim_id": "c1",
        "claimed_at": claimed_at,
        "trigger": "scheduled",
    }
    base.update(over)
    return BriefRecord.model_validate(base)


# ---- settings validation ------------------------------------------------------------------


@pytest.mark.parametrize("value", ["04:00", "07:00", "07:30", "11:30"])
def test_valid_brief_times(value: str) -> None:
    assert parse_brief_time(value).strftime("%H:%M") == value


@pytest.mark.parametrize(
    "value", ["03:30", "11:45", "12:00", "07:15", "7:00", "07:00:00", "", "ab:cd", "24:00", None]
)
def test_invalid_brief_times_are_refused(value: object) -> None:
    with pytest.raises(ValueError, match="04:00"):
        parse_brief_time(value)  # type: ignore[arg-type]


def test_settings_defaults_and_frozen() -> None:
    s = BriefSettings()
    assert (s.enabled, s.time, s.ai_summary, s.inbox_delivery) == (True, "07:00", False, False)
    with pytest.raises(ValueError):
        BriefSettings(time="13:00")
    with pytest.raises(ValidationError, match="frozen"):
        s.enabled = False  # type: ignore[misc]


# ---- local date / due time ----------------------------------------------------------------


def test_local_date_crosses_the_day_boundary() -> None:
    # 23:45 UTC on the 14th is already 05:15 on the 15th in India
    assert local_date(_utc("2027-01-14T23:45:00+00:00"), IST) == date(2027, 1, 15)
    assert local_date(_utc("2027-01-14T23:45:00+00:00"), NY) == date(2027, 1, 14)


def test_due_at_is_local_wall_time_across_dst() -> None:
    # New York springs forward on 2027-03-14: 07:00 local is 11:00Z after, 12:00Z before
    before = due_at(BriefSettings(), date(2027, 3, 13), NY)
    after = due_at(BriefSettings(), date(2027, 3, 14), NY)
    assert before.astimezone(UTC).hour == 12 and after.astimezone(UTC).hour == 11


# ---- is_due -------------------------------------------------------------------------------


def test_not_due_before_the_time() -> None:
    assert not is_due(now=_utc("2027-01-15T06:59:00+05:30"), settings=BriefSettings(), tz=IST)


def test_due_exactly_at_the_time_and_within_catch_up() -> None:
    s = BriefSettings()
    assert is_due(now=_utc("2027-01-15T07:00:00+05:30"), settings=s, tz=IST)
    assert is_due(now=_utc("2027-01-15T10:59:00+05:30"), settings=s, tz=IST)
    assert not is_due(now=_utc("2027-01-15T11:00:00+05:30"), settings=s, tz=IST)
    assert CATCH_UP == timedelta(hours=4)


def test_disabled_is_never_due() -> None:
    off = BriefSettings(enabled=False)
    assert not is_due(now=_utc("2027-01-15T07:30:00+05:30"), settings=off, tz=IST)


def test_ready_brief_is_not_due_again() -> None:
    now = _utc("2027-01-15T07:30:00+05:30")
    rec = _record("ready", now - timedelta(minutes=29))
    assert not is_due(now=now, settings=BriefSettings(), tz=IST, existing=rec)


def test_fresh_claim_is_skipped_and_stale_claim_retaken() -> None:
    now = _utc("2027-01-15T07:30:00+05:30")
    fresh = _record("generating", now - timedelta(minutes=9))
    stale = _record("generating", now - STALE_CLAIM - timedelta(seconds=1))
    assert not is_due(now=now, settings=BriefSettings(), tz=IST, existing=fresh)
    assert is_due(now=now, settings=BriefSettings(), tz=IST, existing=stale)
    assert claim_is_stale(stale, now) and not claim_is_stale(fresh, now)


def test_failed_brief_is_retried_inside_the_window() -> None:
    now = _utc("2027-01-15T08:00:00+05:30")
    rec = _record("failed", now - timedelta(minutes=30))
    assert is_due(now=now, settings=BriefSettings(), tz=IST, existing=rec)


def test_delivery_window_matches_the_catch_up_window() -> None:
    s = BriefSettings(time="06:30")
    assert not in_delivery_window(_utc("2027-01-15T06:29:00+05:30"), s, IST)
    assert in_delivery_window(_utc("2027-01-15T06:30:00+05:30"), s, IST)
    assert not in_delivery_window(_utc("2027-01-15T10:30:00+05:30"), s, IST)


def test_inbox_state_default_is_off() -> None:
    assert InboxState().status == "off"
