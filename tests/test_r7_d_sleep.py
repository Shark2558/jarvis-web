# tests/test_r7_d_sleep.py -- R7 Part D (docs/plans/r7-mobile.md D18): sleep is plain code. "Last
# night" is the longest session ending between 00:00 and 14:00 where he slept, among the sessions of
# one writer (the watch before the phone); a night he typed wins. Sums across midnight, beside a
# nap, with two sessions, across a time-zone change and with no stages; the week is the average and
# the spread of bedtimes. The brief's pinned line names the source.
from __future__ import annotations

from datetime import date

import pytest

from jarvis.brief.models import SleepLine
from jarvis.watch.models import Session, Stages
from jarvis.watch.sleep import brief_text, hm, last_night, sleep_line, week

DAY = date(2026, 11, 12)
IST = "+05:30"
WATCH, PHONE = "com.noisefit", "android"


def s(start: str, end: str, writer: str = WATCH, stages: Stages | None = None) -> Session:
    return Session(start=start, end=end, writer=writer, stages=stages)


def at(d: str, t: str, off: str = IST) -> str:
    return f"2026-11-{d}T{t}:00{off}"


def test_a_night_across_midnight() -> None:
    n = last_night(DAY, [s(at("11", "23:50"), at("12", "06:30"))])
    assert n is not None
    assert (n.minutes, n.start, n.end, n.source) == (400, "23:50", "06:30", "watch")
    assert hm(n.minutes) == "6 h 40 min"


def test_a_nap_is_never_last_night_and_never_beats_the_night() -> None:
    nap = s(at("12", "14:30"), at("12", "15:10"))
    assert last_night(DAY, [nap]) is None  # ends after 14:00
    morning_nap = s(at("12", "12:00"), at("12", "13:00"))
    night = s(at("11", "23:00"), at("12", "06:00"))
    n = last_night(DAY, [morning_nap, night, nap])
    assert n is not None and (n.start, n.end, n.minutes) == ("23:00", "06:00", 420)


def test_two_sessions_keep_the_longest() -> None:
    first = s(at("11", "23:00"), at("12", "02:00"))
    second = s(at("12", "03:00"), at("12", "07:15"))
    n = last_night(DAY, [first, second])
    assert n is not None and (n.start, n.end, n.minutes) == ("03:00", "07:15", 255)


def test_a_time_zone_change_sums_by_the_clock_not_by_the_digits() -> None:
    flown = s(at("11", "23:50"), at("12", "03:30", "+04:00"))  # 18:20 UTC to 23:30 UTC
    n = last_night(DAY, [flown])
    assert n is not None and n.minutes == 310 and (n.start, n.end) == ("23:50", "03:30")


def test_no_stages_means_none_and_stages_are_kept_when_the_watch_wrote_them() -> None:
    plain = last_night(DAY, [s(at("11", "23:50"), at("12", "06:30"))])
    assert plain is not None and plain.stages is None
    staged = Stages(awake=12, light=210, deep=80, rem=98)
    n = last_night(DAY, [s(at("11", "23:50"), at("12", "06:30"), stages=staged)])
    assert n is not None and n.stages == staged


def test_the_watch_is_kept_before_the_phone_and_the_phone_alone_is_named() -> None:
    phone = s(at("11", "22:30"), at("12", "07:00"), PHONE)  # longer, but the phone's guess
    watch = s(at("11", "23:50"), at("12", "06:30"), WATCH)
    n = last_night(DAY, [phone, watch])
    assert n is not None and (n.source, n.minutes) == ("watch", 400)
    alone = last_night(DAY, [phone])
    assert alone is not None and alone.source == "phone"


def test_a_session_that_ended_yesterday_is_not_last_night() -> None:
    assert last_night(DAY, [s(at("10", "23:00"), at("11", "06:00"))]) is None


def test_a_typed_night_wins() -> None:
    typed = Session(start=at("11", "23:30"), end=at("12", "06:00"), writer="typed")
    n = last_night(DAY, [s(at("11", "23:50"), at("12", "06:30"))], typed=typed)
    assert n is not None and (n.source, n.start, n.end, n.minutes) == (
        "typed",
        "23:30",
        "06:00",
        390,
    )


@pytest.mark.parametrize(
    ("minutes", "words"),
    [(0, "0 min"), (45, "45 min"), (60, "1 h"), (400, "6 h 40 min"), (1440, "24 h")],
)
def test_minutes_in_words(minutes: int, words: str) -> None:
    assert hm(minutes) == words


def test_the_week_is_the_average_and_the_spread_of_bedtimes_across_midnight() -> None:
    nights = []
    for d, bed, up in (
        ("06", "23:10", "06:40"),
        ("07", "00:40", "07:10"),
        ("09", "23:50", "07:00"),
    ):
        prev = f"{int(d) - 1:02d}"
        start = at(prev if bed > "12:00" else d, bed)
        n = last_night(date(2026, 11, int(d)), [s(start, at(d, up))])
        assert n is not None
        nights.append(n)
    w = week(nights)
    assert w is not None
    assert w.nights == 3 and w.bed_from == "23:10" and w.bed_to == "00:40"
    assert w.avg_minutes == round((450 + 390 + 430) / 3)
    assert week([]) is None


def test_the_briefs_line_names_the_source() -> None:
    n = last_night(DAY, [s(at("11", "23:50"), at("12", "06:30"))])
    assert n is not None
    line = sleep_line(n)
    assert line == SleepLine(minutes=400, start="23:50", end="06:30", source="watch")
    assert brief_text(line) == "Sleep: 6 h 40 min, 23:50 to 06:30 · from your watch"
    phone = SleepLine(minutes=60, start="05:00", end="06:00", source="phone")
    typed = SleepLine(minutes=60, start="05:00", end="06:00", source="typed")
    assert brief_text(phone).endswith("· from your phone")
    assert brief_text(typed).endswith("· typed by you")


def test_another_app_comes_after_the_phone_and_is_named_neutrally() -> None:
    other = "com.example.makerhealth"
    app_night = s(at("11", "22:00"), at("12", "07:30"), other)  # the longest, but neither
    phone = s(at("11", "23:00"), at("12", "06:00"), PHONE)
    n = last_night(DAY, [app_night, phone])
    assert n is not None and n.source == "phone"
    alone = last_night(DAY, [app_night])
    assert alone is not None and alone.source == "app"
    # I1: the brief's pinned shape knows "app" too, so another health app is named as itself
    assert sleep_line(alone).source == "app"
    assert brief_text(sleep_line(alone)).endswith("· from another health app")
