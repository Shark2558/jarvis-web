# src/jarvis/selfwatch/vitals.py
"""Part B's Vitals item `clocks` ("JARVIS's clocks", docs/plans/r14-hardening.md D5, review A8):
an ordinary Vitals item, sent by the server through I0's slot (`vitals.own.OwnSources.r14`), so
the console is untouched. Quiet on the board (`hardening.ports.VITALS_QUIET`): the clocks speak
through their own kinds; this item is what he sees when BOTH clocks stopped and nothing can
speak up ("Clocks stopped since …").

- the 5-minute clock is running when it ran within `WATCHDOG_GAP` (20 minutes);
- the morning clock is running when it ran within `TICK_STALE` and, after 05:00, today;
- a clock never seen yet is neither (a fresh start), so "not seen yet" until one runs.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from jarvis.selfwatch.clocks import TICK_BY, WATCHDOG_GAP, ClockState
from jarvis.vitals.own import OwnItem, own_item

PID = "clocks"
TICK_STALE = timedelta(hours=26)  # yesterday's last tick (11:30) is fine until 05:00


def _tick_ok(tick: datetime | None, now: datetime, tz: ZoneInfo) -> bool | None:
    if tick is None:
        return None
    local = now.astimezone(tz)
    if now - tick > TICK_STALE:
        return False
    return not (local.time() >= TICK_BY and tick.astimezone(tz).date() < local.date())


def _dog_ok(dog: datetime | None, now: datetime) -> bool | None:
    return None if dog is None else now - dog <= WATCHDOG_GAP


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
    dog, tick = _dog_ok(s.watchdog, now), _tick_ok(s.tick, now, tz)
    if dog is None and tick is None:
        note = "JARVIS hasn't seen its clocks run yet; the 5-minute clock runs within 5 minutes."
        return own_item(PID, "unknown", "not seen yet", note=note)
    if dog is not True and tick is not True:
        latest = max(at for at in (s.watchdog, s.tick) if at is not None)
        return own_item(
            PID, "red", "have stopped", note=f"Clocks stopped since {_when(latest, tz)}."
        )
    if dog is False and s.watchdog is not None:
        note = f"The 5-minute clock last ran at {_when(s.watchdog, tz)}; the morning clock runs."
        return own_item(PID, "amber", "one has stopped", note=note)
    if tick is False:
        note = "The morning clock didn't run when it should have; the 5-minute clock runs."
        return own_item(PID, "amber", "one has stopped", note=note)
    return own_item(PID, "ok", "are running", note=_running_note(s, now, tz))


__all__ = ["PID", "TICK_STALE", "clocks_item"]
