# src/jarvis/selfwatch/vitals.py
"""Part B's Vitals item `clocks` ("JARVIS's clocks", docs/plans/r14-hardening.md D5, review A8):
an ordinary Vitals item, sent by the server through I0's slot (`vitals.own.OwnSources.r14`), so
the console is untouched. Quiet on the board (`hardening.ports.VITALS_QUIET`): the clocks speak
through their own kinds; this item is what he sees when BOTH clocks stopped and nothing can
speak up ("Clocks stopped since …").

- the 5-minute clock is running when it ran within `WATCHDOG_GAP` (20 minutes);
- the morning clock is running when it ran within `TICK_STALE` and, after 05:00, today;
- a clock never seen is judged from the baseline (`clocks.first_seen`), as its alert is: not
  in a fresh install's first hour, stopped once it should have run; with no clock seen at all,
  "not seen yet".
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from jarvis.selfwatch.clocks import TICK_BY, WATCHDOG_GAP, ClockState, tick_due, watchdog_stopped
from jarvis.vitals.own import OwnItem, own_item

PID = "clocks"
TICK_STALE = timedelta(hours=26)  # yesterday's last tick (11:30) is fine until 05:00


def _tick_ok(s: ClockState, now: datetime, tz: ZoneInfo) -> bool | None:
    tick = s.tick
    if tick is None:
        due = tick_due(s, tz)
        return False if due is not None and now >= due else None
    local = now.astimezone(tz)
    if now - tick > TICK_STALE:
        return False
    return not (local.time() >= TICK_BY and tick.astimezone(tz).date() < local.date())


def _dog_ok(s: ClockState, now: datetime) -> bool | None:
    if s.watchdog is None:
        never = watchdog_stopped(replace(s, watchdog_outage=None), now) is not None
        return False if never else None
    return now - s.watchdog <= WATCHDOG_GAP


def _when(at: datetime, tz: ZoneInfo) -> str:
    d = at.astimezone(tz)
    return f"{d.day} {d:%b}, {d:%H:%M}"


def _ago(at: datetime, now: datetime) -> str:
    minutes = max(0, int((now - at).total_seconds() // 60))
    if minutes < 1:
        return "just now"
    return f"{minutes} minute{'' if minutes == 1 else 's'} ago"


def _running_note(s: ClockState, now: datetime, tz: ZoneInfo) -> str:
    dog = "hasn't run yet" if s.watchdog is None else f"ran {_ago(s.watchdog, now)}"
    tick = "hasn't run yet" if s.tick is None else f"ran at {_when(s.tick, tz)}"
    return f"The 5-minute clock {dog}; the morning clock {tick}."


def clocks_item(s: ClockState, now: datetime, tz: ZoneInfo) -> OwnItem:
    dog, tick = _dog_ok(s, now), _tick_ok(s, now, tz)
    if dog is None and tick is None:
        note = "JARVIS hasn't seen its clocks run yet; the 5-minute clock runs within 5 minutes."
        return own_item(PID, "unknown", "not seen yet", note=note)
    if dog is not True and tick is not True:
        latest = max(at for at in (s.watchdog, s.tick, s.first_seen) if at is not None)
        return own_item(
            PID, "red", "have stopped", note=f"Clocks stopped since {_when(latest, tz)}."
        )
    if dog is False and s.watchdog is not None:
        note = f"The 5-minute clock last ran at {_when(s.watchdog, tz)}; the morning clock runs."
        return own_item(PID, "amber", "one has stopped", note=note)
    if dog is False:
        note = "The 5-minute clock hasn't run since JARVIS started; the morning clock runs."
        return own_item(PID, "amber", "one has stopped", note=note)
    if tick is False:
        note = "The morning clock didn't run when it should have; the 5-minute clock runs."
        return own_item(PID, "amber", "one has stopped", note=note)
    return own_item(PID, "ok", "are running", note=_running_note(s, now, tz))


__all__ = ["PID", "TICK_STALE", "clocks_item"]
