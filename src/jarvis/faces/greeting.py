# src/jarvis/faces/greeting.py
"""Greeting rules (R3 D13, D10). Greetings in R3 are text: a feed line on the owner's console and,
if he switched Greeting alerts on (default off), an `info` alert.

- Only someone `Directory.resolve` named is greeted by name, and only on the console feed
  ("Anjali arrived at the Gate, 18:42"). Everyone else is "someone JARVIS didn't recognise".
- Off the console (Telegram, browser notifications, speech) the words come from `alert_words`: a
  child is never named, an adult only with "Say names in alerts" on.
- One greeting per person per 30 minutes (`GreetingLimiter`, in-process: one instance).
- A greeting never replaces or lowers an alert: it is only ever added (recognition raises).
"""

from __future__ import annotations

import time
from collections.abc import Callable

from jarvis.faces.directory import alert_words
from jarvis.faces.ports import UNKNOWN_PERSON, Resolved

GREETING_GAP_S = 30 * 60
MAX_TRACKED = 200
_PLACE_MAX = 30


def _place(camera_label: str) -> str:
    return " ".join(str(camera_label).split())[:_PLACE_MAX] or "the camera"


def feed_line(who: Resolved, camera_label: str, at_local: str) -> str:
    """The console feed's words. The console is the owner's own screen, so a named person (a child
    too) is named there; an unnamed one never is."""
    name = who.name if who.named and who.name else UNKNOWN_PERSON
    return f"{name} arrived at {_place(camera_label)}, {at_local}"


def alert_line(who: Resolved, camera_label: str, at_local: str, *, say_names: bool) -> str:
    """The words for Telegram, Web Push or speech (<= 300 characters, fixed template)."""
    return f"{alert_words(who, say_names=say_names)} arrived at {_place(camera_label)}, {at_local}"[
        :300
    ]


class GreetingLimiter:
    """True at most once per person per 30 minutes. Unnamed people are never greeted."""

    def __init__(self, now: Callable[[], float] = time.time) -> None:
        self._now = now
        self._last: dict[str, float] = {}

    def allow(self, who: Resolved) -> bool:
        if not who.named or who.person is None:
            return False
        now = self._now()
        last = self._last.get(who.person)
        if last is not None and now - last < GREETING_GAP_S:
            return False
        if len(self._last) >= MAX_TRACKED:
            self._last = {p: t for p, t in self._last.items() if now - t < GREETING_GAP_S}
        self._last[who.person] = now
        return True


__all__ = ["GREETING_GAP_S", "GreetingLimiter", "alert_line", "feed_line"]
