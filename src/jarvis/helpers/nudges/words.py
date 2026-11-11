# src/jarvis/helpers/nudges/words.py
"""Part C's fixed words: how a nudge's settings read, and the tools' argument parsing (a No-AI call
passes every argument as text, the model may pass numbers and booleans: both are accepted).
"""

from __future__ import annotations

import re
from typing import Any

from jarvis.helpers.nudges.models import (
    ALL,
    EVERY_KINDS,
    LABEL,
    TIMES_KINDS,
    WEEK,
    WORKWEEK,
    Nudge,
    kind_of,
)

DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_DAY_SETS = {
    "every day": WEEK,
    "daily": WEEK,
    "all week": WEEK,
    "weekdays": (0, 1, 2, 3, 4),
    "monday to friday": (0, 1, 2, 3, 4),
    "mon-fri": (0, 1, 2, 3, 4),
    "monday to saturday": WORKWEEK,
    "mon-sat": WORKWEEK,
    "weekends": (5, 6),
}
_YES = {"true", "yes", "on", "1"}
_NO = {"false", "no", "off", "0"}


def days_text(days: tuple[int, ...]) -> str:
    if days == WEEK:
        return "every day"
    if days == WORKWEEK:
        return "Monday to Saturday"
    if days == (0, 1, 2, 3, 4):
        return "Monday to Friday"
    return ", ".join(DAY_NAMES[d][:3] for d in days)


def describe(kind: str, n: Nudge) -> str:
    """One line in JARVIS's words: "Drink water: on, every 90 minutes, 09:30-18:30, ..."."""
    parts = [f"{LABEL[kind]}: {'on' if n.on else 'off'}"]
    if kind in EVERY_KINDS:
        parts.append(f"every {n.every} minutes, {n.start}-{n.end}")
    elif kind in TIMES_KINDS:
        parts.append("at " + ", ".join(n.times))
    else:
        parts.append(f"{n.start}-{n.end}, for " + ", ".join(n.words))
    parts.append(days_text(n.days))
    if kind == "nudge_standup" and n.meeting:
        parts.append(f"and 10 minutes before your '{n.word}' meeting")
    return ", ".join(parts) + "."


def a_kind(value: Any, *, allow_all: bool = True) -> str:
    kind = kind_of(str(value or ""))
    if kind == ALL and not allow_all:
        raise ValueError("Name one nudge, Sir: stand-up, water, activity, free time or focus.")
    return kind


def a_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    word = str(value).strip().lower()
    if word in _YES:
        return True
    if word in _NO:
        return False
    raise ValueError("Say on or off, Sir.")


def a_number(value: Any, *, lo: int, hi: int, what: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{what} must be a whole number")
    text = str(value).strip()
    if not re.fullmatch(r"\d{1,4}", text):
        raise ValueError(f"{what} must be a whole number")
    n = int(text)
    if not lo <= n <= hi:
        raise ValueError(f"{what} must be {lo} to {hi}")
    return n


def a_list(value: Any) -> tuple[str, ...]:
    items = value if isinstance(value, list | tuple) else re.split(r"[,;]| and ", str(value))
    return tuple(s for s in (" ".join(str(x).split()) for x in items) if s)


def a_days(value: Any) -> tuple[int, ...]:
    key = " ".join(str(value).lower().split()) if isinstance(value, str) else ""
    if key in _DAY_SETS:
        return _DAY_SETS[key]
    out = []
    for item in a_list(value):
        low = item.lower()
        found = [i for i, name in enumerate(DAY_NAMES) if name.lower().startswith(low[:3])]
        if len(low) < 3 or not found:
            raise ValueError("Days are names (Monday, Tue, ...), 'weekdays' or 'every day'.")
        out.append(found[0])
    return tuple(sorted(set(out)))


def changes(args: dict[str, Any]) -> dict[str, Any]:
    """`nudge_set`'s arguments as `Nudge` fields (validated again by the model)."""
    out: dict[str, Any] = {}
    if "on" in args:
        out["on"] = a_bool(args["on"])
    if "every_minutes" in args:
        out["every"] = a_number(args["every_minutes"], lo=15, hi=240, what="every_minutes")
    for key in ("start", "end", "word"):
        if key in args:
            out[key] = str(args[key]).strip()
    if "days" in args:
        out["days"] = a_days(args["days"])
    if "times" in args:
        out["times"] = a_list(args["times"])
    if "words" in args:
        out["words"] = tuple(w.lower() for w in a_list(args["words"]))
    if "meeting" in args:
        out["meeting"] = a_bool(args["meeting"])
    return out


__all__ = ["a_bool", "a_days", "a_kind", "a_list", "a_number", "changes", "days_text", "describe"]
