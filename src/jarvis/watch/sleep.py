# src/jarvis/watch/sleep.py
"""Sleep in plain code (docs/plans/r7-mobile.md D18): no model, no advice, fixed words.

- `last_night(day, sessions, typed)`: a night he typed for that day wins; otherwise the longest
  session that ended on `day` between 00:00 and 14:00 by the clock where he slept (each time keeps
  its own UTC offset, so a night across a time-zone change is summed by the clock, and its start
  and end read as the phone showed them), among the sessions of ONE writer: a watch app before
  the phone, any other app after both (D17), and among equals the writer with the longest session
  (the phone's day builder already keeps one writer a night; this holds if two days' lists overlap).
- `week(nights)`: the average and the spread of bedtimes (earliest to latest, across midnight).
- `sleep_line(night)` is the brief's pinned shape (`brief.models.SleepLine`) and `brief_text`
  its one console line: "Sleep: 6 h 40 min, 23:50 to 06:30 · from your watch".
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Literal

from jarvis.brief.models import SleepLine
from jarvis.watch.models import TYPED_WRITER, Session, Source, Stages, source_of

LATEST_END = time(14, 0)  # a night ends by 14:00 his time; later is a nap
NOON_MINUTES = 12 * 60
DAY_MINUTES = 24 * 60
FROM: dict[str, str] = {
    "watch": "from your watch",
    "phone": "from your phone",
    "app": "from another health app",
    "typed": "typed by you",
}
DOT = "·"


@dataclass(frozen=True)
class Night:
    minutes: int
    start: str  # HH:MM where he slept
    end: str
    source: Source
    stages: Stages | None = None


@dataclass(frozen=True)
class Week:
    nights: int
    avg_minutes: int
    bed_from: str
    bed_to: str


def clock(at: datetime) -> str:
    return at.strftime("%H:%M")


def hm(minutes: int) -> str:
    h, m = divmod(max(0, int(minutes)), 60)
    if h and m:
        return f"{h} h {m} min"
    return f"{h} h" if h else f"{m} min"


def _ends_on(session: Session, day: date) -> bool:
    end = session.ended
    return end.date() == day and end.time() <= LATEST_END


def _night(session: Session, source: Source) -> Night:
    return Night(
        minutes=session.minutes,
        start=clock(session.started),
        end=clock(session.ended),
        source=source,
        stages=session.stages if source != "typed" else None,
    )


def _writer_rank(writer: str, sessions: Sequence[Session]) -> tuple[int, int]:
    longest = max(x.minutes for x in sessions if x.writer == writer)
    return ({"watch": 0, "phone": 1}.get(source_of(writer), 2), -longest)


def last_night(
    day: date, sessions: Iterable[Session], typed: Session | None = None
) -> Night | None:
    if typed is not None and _ends_on(typed, day):
        return _night(typed, "typed")
    found = [x for x in sessions if x.writer != TYPED_WRITER and _ends_on(x, day)]
    if not found:
        return None
    # One writer a night (D17): the writer is chosen first (the watch, then the phone, then any other
    # app), then its longest session. A short watch nap inside the window therefore beats a phone
    # night; the phone's day builder keeps ONE writer per day, so the two lists do not overlap.
    writer = min({x.writer for x in found}, key=lambda w: _writer_rank(w, found))
    best = max((x for x in found if x.writer == writer), key=lambda x: x.minutes)
    return _night(best, source_of(writer))


def _bed_minutes(start: str) -> int:
    """Minutes after noon, so 23:10 comes before 00:40."""
    h, m = (int(x) for x in start.split(":"))
    return (h * 60 + m - NOON_MINUTES) % DAY_MINUTES


def week(nights: Sequence[Night]) -> Week | None:
    if not nights:
        return None
    beds = sorted(nights, key=lambda n: _bed_minutes(n.start))
    avg = round(sum(n.minutes for n in nights) / len(nights))
    return Week(len(nights), avg, beds[0].start, beds[-1].start)


def sleep_line(night: Night) -> SleepLine:
    """The brief's pinned shape: its source is watch / phone / typed only, so a night from another
    health app on his phone is written "phone" there (the tools and the Watch tab say "another
    health app")."""
    source: Literal["watch", "phone", "typed"] = "phone" if night.source == "app" else night.source
    return SleepLine(
        minutes=min(night.minutes, DAY_MINUTES),
        start=night.start,
        end=night.end,
        source=source,
    )


def brief_text(line: SleepLine) -> str:
    return f"Sleep: {hm(line.minutes)}, {line.start} to {line.end} {DOT} {FROM[line.source]}"


__all__ = [
    "FROM",
    "LATEST_END",
    "Night",
    "Week",
    "brief_text",
    "clock",
    "hm",
    "last_night",
    "sleep_line",
    "week",
]
