# src/jarvis/wardrobe/styling/texts.py
"""R13 Part C's fixed sentences (D10, D19): every word here is JARVIS's own or a fixed-list word.

A piece is named by its id and its fixed words ("a navy shirt", `redact.fixed_words`; a private
piece "a private basic"), never by his label; an event by its time ("your 10:00 event"), never by
its title. Dates are his local dates, written whole ("Tuesday 17 November"). Alerts end in
"in Helpers, Wardrobe" (D19). Pure: no clock (every day is passed in).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta, tzinfo

from jarvis.wardrobe.model import Piece
from jarvis.wardrobe.redact import PRIVATE_WORDS, fixed_words, type_words
from jarvis.wardrobe.states import STATE_WORDS, State

WEATHER_UNKNOWN = "Weather unknown: I assumed indoors."
PLURAL_TYPES = frozenset(
    {"trousers", "chinos", "jeans", "shorts", "joggers", "underpants", "briefs", "boxers"}
)
WHERE = "in Helpers, Wardrobe"
OFF_NO_KEY = "Outfits are off: JARVIS has no token key to seal your plans."
OFF_NO_STORE = "Outfits are off: no storage is set up."
NOT_READY_YET = "Your wardrobe isn't ready yet: try again in a minute."
NEXT_ACTION: dict[State, str] = {
    "in_laundry": "wash {it}",
    "washing": "{it} {is} in the wash",
    "drying": "{it} {is} drying",
    "needs_prep": "press {it}",
    "with_provider": "collect {it} from the laundry shop",
    "needs_repair": "get {it} repaired",
    "review": "check {it} in Helpers, Wardrobe",
    "in_use": "{it} {is} in use",
    "archived": "{it} {is} archived",
    "ready": "{it} {is} ready",
}
LEFT_WORDS: dict[State, str] = {
    "in_laundry": "went to the laundry",
    "washing": "went to the laundry",
    "drying": "went to the laundry",
    "needs_prep": "needs pressing",
    "with_provider": "went to the laundry shop",
    "needs_repair": "needs a repair",
    "review": "needs a quick check",
    "in_use": "is in use",
    "archived": "was archived",
    "ready": "is ready",
}
_FEATURE_WORDS = {
    "neck": "{v} at the neck",
    "fit": "{v} fit",
    "sleeve": "{v} sleeves",
    "collar": "{v} collars",
    "strap": "a {v} strap",
    "closure": "{v} closures",
    "colour": "{v}",
    "pattern": "{v}",
    "type": "{v}",
}


_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MONTHS = (
    *("January", "February", "March", "April", "May", "June", "July", "August"),
    *("September", "October", "November", "December"),
)


def date_words(day: date) -> str:
    """ "Tuesday 17 November" (fixed English words, whatever the server's locale)."""
    return f"{_DAYS[day.weekday()]} {day.day} {_MONTHS[day.month - 1]}"


def day_words(day: date, today: date) -> str:
    """ "Tomorrow, Tuesday 17 November" / "Today, Monday 16 November" / "Friday 20 November"."""
    lead = {0: "Today, ", 1: "Tomorrow, "}.get((day - today).days, "")
    return f"{lead}{date_words(day)}"


def ids_words(ids: Sequence[str]) -> str:
    items = list(ids)
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def piece_words(p: Piece) -> str:
    """ "a navy shirt", "charcoal trousers" (a type that is always plural takes no "a")."""
    words = fixed_words(p).replace("_", " ")
    if not p.private and p.type in PLURAL_TYPES and words.startswith("a "):
        return words[2:]
    return words


def unit_words(pieces: Sequence[Piece]) -> str:
    """One piece's words, or "a pair of brown dress shoes" for a pair."""
    if len(pieces) != 2 or any(p.private for p in pieces):
        return " and ".join(piece_words(p) for p in pieces)
    colour = (pieces[0].colour or "").replace("_", " ")
    kind = type_words(pieces[0])
    plural = kind if kind.endswith("s") else f"{kind}s"
    return " ".join(w for w in ("a pair of", colour, plural) if w)


def private_view_words(p: Piece) -> str:
    """His own panel with "Show private basics" on: the colour and type of a private piece."""
    colour = (p.colour or "").replace("_", " ")
    article = "" if p.type in PLURAL_TYPES else "a"
    return " ".join(w for w in (article, colour, type_words(p)) if w)


def never_words(feature: str, value: str) -> str:
    v = value.replace("_", " ")
    return _FEATURE_WORDS.get(feature, "{v}").format(v=v)


def next_action(state: State, n: int) -> str:
    it, is_ = ("them", "are") if n > 1 else ("it", "is")
    return NEXT_ACTION[state].format(it=it, **{"is": is_})


def states_line(pieces: Sequence[Piece]) -> str:
    """ "wi_1 and wi_2 are In laundry (wash them)" for each state the pieces are in."""
    parts = []
    for state in dict.fromkeys(p.state for p in pieces):
        ids = [p.id for p in pieces if p.state == state]
        verb = "are" if len(ids) > 1 else "is"
        todo = next_action(state, len(ids))
        parts.append(f"{ids_words(ids)} {verb} {STATE_WORDS[state]} ({todo})")
    return "; ".join(parts)


def local_time(at: datetime, zone: tzinfo) -> str:
    return at.astimezone(zone).strftime("%H:%M")


def event_words(starts: datetime | None, zone: tzinfo) -> str:
    return f"your {local_time(starts, zone)} event" if starts is not None else "your plan"


def whose(day: date, today: date) -> str:
    """ "today's" / "tomorrow's" / "Friday's"."""
    gap = (day - today).days
    return {0: "today's", 1: "tomorrow's"}.get(gap, f"{_DAYS[day.weekday()]}'s")


def outfit_label(day: date, today: date, starts: datetime | None, zone: tzinfo) -> str:
    """ "tomorrow's 10:00 outfit" / "today's outfit"."""
    at = f" {local_time(starts, zone)}" if starts is not None else ""
    return f"{whose(day, today)}{at} outfit"


def changed_alert(p: Piece, label: str, *, proposal: bool) -> str:
    """outfit_changed (D19): fixed words, never his label, a title or a private piece's words."""
    who = piece_words(p)
    first = f"{who[0].upper()}{who[1:]} in {label} {LEFT_WORDS[p.state]}."
    rest = f"A ready one is suggested {WHERE}." if proposal else f"None is ready: look {WHERE}."
    return f"{first} {rest}"


def ready_alert(label: str, gaps: int) -> str:
    """outfit_ready (D19), the evening before."""
    base = f"{label[0].upper()}{label[1:]} is ready {WHERE}"
    if gaps:
        return f"{base}, with {gaps} gap{'s' if gaps > 1 else ''} to fix."
    return f"{base}."


def ready_more_alert(day: date, today: date, more: int) -> str:
    """outfit_ready past the evening's first three (security review H1): one line for the rest."""
    who, s = whose(day, today), "s" if more > 1 else ""
    return f"{who[0].upper()}{who[1:]} outfits for {more} more event{s} are ready {WHERE}."


def ready_event_label(day: date, today: date, starts: datetime | None, zone: tzinfo) -> str:
    """ "tomorrow's outfit for your 10:00 event"."""
    return f"{whose(day, today)} outfit for {event_words(starts, zone)}"


def tomorrow_of(now: datetime, zone: tzinfo) -> date:
    return now.astimezone(zone).date() + timedelta(days=1)


__all__ = [
    "LEFT_WORDS",
    "NEXT_ACTION",
    "NOT_READY_YET",
    "OFF_NO_KEY",
    "OFF_NO_STORE",
    "PRIVATE_WORDS",
    "WEATHER_UNKNOWN",
    "WHERE",
    "changed_alert",
    "date_words",
    "day_words",
    "event_words",
    "ids_words",
    "local_time",
    "never_words",
    "next_action",
    "outfit_label",
    "piece_words",
    "private_view_words",
    "ready_alert",
    "ready_event_label",
    "ready_more_alert",
    "states_line",
    "tomorrow_of",
    "unit_words",
    "whose",
]
