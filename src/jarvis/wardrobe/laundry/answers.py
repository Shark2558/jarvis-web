# src/jarvis/wardrobe/laundry/answers.py
"""R13 Part B: what an open review entry may be answered with, in ONE place (INTEGRATION-B 6.6).

The resolver (`resolve.py`) and the panel's `ReviewEntry.answers` both read this, so the panel
can never offer an answer the resolver refuses or hide one it accepts. An entry is answered by
its FAMILY, never by its reason word (an older repair used the reason "sweep"):

- a hold is answered by the PIECES' own holds: `none` ("it didn't happen") only when every
  piece it names is held on an unconfirmed change;
- B's own "which one?" (it carries the step he asked for) takes these, none or dismiss;
- every other rescan (A's "corrected", another part's) and every "check this place" is a check:
  a sighting where it is (`these`), a new place (`moved`), or dismissed.
"""

from __future__ import annotations

from collections.abc import Mapping

from jarvis.wardrobe.laundry.store import Entry
from jarvis.wardrobe.model import WardrobeView

ORDER: tuple[str, ...] = ("these", "none", "moved", "dismiss")
OUTCOMES: Mapping[str, frozenset[str]] = {
    "pending_deposit": frozenset({"these", "none"}),
    "which": frozenset({"these", "none", "dismiss"}),
    "hold": frozenset({"these", "none", "moved"}),
    "conflict": frozenset({"these", "none", "dismiss"}),
    "stale": frozenset({"these", "moved", "dismiss"}),
}


def family(e: Entry) -> str:
    """How an entry is answered (never a default clean return: review H1)."""
    if e.kind == "rescan":
        if e.reason == "blind":
            return "hold"
        return "which" if e.reason == "which" and e.step else "stale"
    return "stale" if e.kind == "place" else e.kind


def answers_of(e: Entry, view: WardrobeView | None = None) -> tuple[str, ...]:
    """The outcomes this entry takes, in one fixed order. Given the view, a hold drops `none`
    when any piece it names is held on something other than an unconfirmed change."""
    allowed = set(OUTCOMES[family(e)])
    if family(e) == "hold" and view is not None:
        live = (view.pieces.get(pid) for pid in e.pieces)
        if any(
            p is not None and p.state == "review" and p.hold not in (None, "unverified")
            for p in live
        ):
            allowed.discard("none")
    return tuple(o for o in ORDER if o in allowed)


__all__ = ["ORDER", "OUTCOMES", "answers_of", "family"]
