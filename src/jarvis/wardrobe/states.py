# src/jarvis/wardrobe/states.py
"""R13 D3 (docs/plans/r13-wardrobe.md): the workbook's "Item status and availability" table.

The 10 states, which one is eligible for an outfit, and the transitions each event kind may make.
Every part reads this one table: A's fold (and the I0 reference fold in `tests/r13_fakes_store.py`,
held to the same rules by `tests/test_r13_fold_conformance.py`), A's counts, B's half-pair rule and
C's engine. Pure: no I/O, no clock.

How a target is decided (`target_of`):
- a fixed target (`deposited` -> In laundry);
- `STATED`: the state the event says (`Event.to`) from `STATED_CHOICES`, else the kind's default
  (`wear_done`: the rewear rule's answer, In laundry by default; `registered`: Ready);
- `KEEP`: the current state (`seen`, `lifted`: a place, not a state);
- `BACK`: the `back_to` the hold remembered (`released`; `found` without a stated state).
An event whose target equals the current state is a `duplicate` (a second record of the same
movement, plan M3) unless it moves the piece or hands a wear to another plan; that check comes
before the sources check, so a second deposit never opens a review.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Final, Literal, get_args

State = Literal[
    "ready",
    "in_use",
    "in_laundry",
    "washing",
    "drying",
    "needs_prep",
    "with_provider",
    "needs_repair",
    "review",
    "archived",
]
STATES: tuple[State, ...] = get_args(State)
STATE_WORDS: Mapping[State, str] = MappingProxyType(
    {
        "ready": "Ready",
        "in_use": "In use",
        "in_laundry": "In laundry",
        "washing": "Washing",
        "drying": "Drying",
        "needs_prep": "Needs prep",
        "with_provider": "With laundry provider",
        "needs_repair": "Needs repair",
        "review": "Missing or in review",
        "archived": "Archived",
    }
)
EventKind = Literal[
    "registered",
    "seen",
    "wear_started",
    "wear_done",
    "deposited",
    "lifted",
    "load_started",
    "dried",
    "needs_prep",
    "returned",
    "sent_out",
    "received",
    "damaged",
    "repaired",
    "held",
    "released",
    "missing",
    "found",
    "archived",
    "restored",
    "merged",
    "corrected",
    "blind",
]
EVENT_KINDS: tuple[EventKind, ...] = get_args(EventKind)

STATED: Final = "stated"
KEEP: Final = "keep"
BACK: Final = "back"
Target = State | Literal["stated", "keep", "back"]
NEW: Final = None  # a piece with no history yet

_LAUNDRY: frozenset[State] = frozenset({"in_laundry", "washing", "drying", "needs_prep"})
_ACTIVE: frozenset[State] = frozenset(STATES) - {"archived"}
_WORN_OR_READY: frozenset[State] = frozenset({"ready", "in_use"})


class Rule:
    """One row: the states it may start from (`NEW` allowed or not) and its target."""

    __slots__ = ("from_new", "sources", "target")

    def __init__(self, sources: frozenset[State], target: Target, *, from_new: bool = False):
        self.sources, self.target, self.from_new = sources, target, from_new

    def __repr__(self) -> str:
        return f"Rule({sorted(self.sources)}, {self.target!r}, from_new={self.from_new})"


_ANY = _ACTIVE
TRANSITIONS: Mapping[EventKind, Rule] = MappingProxyType(
    {
        "registered": Rule(frozenset(), STATED, from_new=True),
        "seen": Rule(_ANY, KEEP, from_new=True),  # an intake makes it Ready; else a sighting
        "wear_started": Rule(_WORN_OR_READY, "in_use"),  # In use -> In use: a declared hand-off
        "wear_done": Rule(frozenset({"in_use"}), STATED),
        "deposited": Rule(_WORN_OR_READY, "in_laundry"),
        "lifted": Rule(frozenset({"in_laundry"}), KEEP),  # a new place; the hold stays
        "load_started": Rule(frozenset({"in_laundry"}), "washing"),
        "dried": Rule(frozenset({"washing"}), "drying"),
        "needs_prep": Rule(frozenset({"drying"}), "needs_prep"),
        "returned": Rule(_LAUNDRY, "ready"),  # with a place
        "sent_out": Rule(frozenset({"ready", "in_use", *_LAUNDRY}), "with_provider"),
        "received": Rule(frozenset({"with_provider"}), STATED),
        "damaged": Rule(_ANY - {"review", "needs_repair"}, "needs_repair"),
        "repaired": Rule(frozenset({"needs_repair"}), "ready"),
        "held": Rule(_ANY, "review"),  # back_to kept
        "released": Rule(frozenset({"review"}), BACK),
        "missing": Rule(_ANY, "review"),  # back_to kept
        "found": Rule(frozenset({"review"}), STATED),  # the state he confirms, else back_to
        "archived": Rule(_ANY, "archived"),
        "restored": Rule(frozenset({"archived"}), "review"),  # until he confirms its condition
        "merged": Rule(_ANY, "archived"),  # the merged-away id: a tombstone (D16)
        "corrected": Rule(frozenset(STATES), KEEP, from_new=True),  # voids another event (D4)
        "blind": Rule(_ANY, "review"),  # OPS-02: held until a rescan or his correction
    }
)
# The state an event names (`Event.to`) and its default when it names none.
STATED_CHOICES: Mapping[EventKind, tuple[State, ...]] = MappingProxyType(
    {
        "registered": ("ready", "in_use", "in_laundry", "needs_prep", "needs_repair", "review"),
        "wear_done": ("in_laundry", "ready"),
        "received": ("ready", "needs_prep"),
        "found": tuple(s for s in STATES if s not in ("review", "archived")),
    }
)
STATED_DEFAULT: Mapping[EventKind, State | None] = MappingProxyType(
    {"registered": "ready", "wear_done": "in_laundry", "received": "ready", "found": None}
)
# Kinds that set a state (a sighting, a lift and a correction set none).
STATE_SETTING: frozenset[EventKind] = frozenset(EVENT_KINDS) - {"seen", "lifted", "corrected"}
# Kinds only a card makes (D16, INV-17): a correction never voids one. One set: A's store and
# B's corrections and history import it (Workshop decision 2).
CARD_ONLY: frozenset[EventKind] = frozenset(
    {"registered", "archived", "restored", "merged", "corrected"}
)
# Kinds that remember the latest verified state, to go back to (LND-04, OPS-02).
HOLDING: frozenset[EventKind] = frozenset({"held", "missing", "blind"})
# Only Ready is eligible (and In use, for a later plan the same day that declares it shared with
# the plan it is worn for, when the rewear rule allows: C's engine decides that hand-off).
ELIGIBLE: frozenset[State] = frozenset({"ready"})
COUNTED: frozenset[State] = _ACTIVE  # owned and counted: everything but Archived (INV-14)


def eligible(state: State | None) -> bool:
    return state in ELIGIBLE


def owned(state: State | None) -> bool:
    return state in COUNTED


def wearable_pair(states: Sequence[State | None]) -> bool:
    """A pair is wearable only while both of its pieces are eligible (INV-11, LND-13)."""
    return len(states) == 2 and all(eligible(s) for s in states)


def wearable_set(parts: Sequence[tuple[State | None, bool]]) -> tuple[bool, tuple[int, ...]]:
    """(the whole set is wearable, the indexes of parts eligible and wearable alone) (INV-12).
    `parts`: each part's state and whether it "can be worn alone"."""
    whole = 2 <= len(parts) <= 6 and all(eligible(s) for s, _ in parts)
    alone = tuple(i for i, (s, ok) in enumerate(parts) if ok and eligible(s))
    return whole, alone


def stated(kind: EventKind, to: State | None, back_to: State | None) -> State | None:
    """The state a STATED kind lands in: his word when it is one of the kind's choices, else the
    default (for `found`, the remembered `back_to`, else Ready)."""
    choices = STATED_CHOICES.get(kind, ())
    if to is not None and to in choices:
        return to
    if to is not None:
        return None  # a state this kind can't name: refused
    default = STATED_DEFAULT.get(kind)
    if default is None and kind == "found":
        return back_to if back_to not in (None, "review", "archived") else "ready"
    return default


def target_of(
    kind: EventKind, current: State | None, *, to: State | None = None, back_to: State | None = None
) -> State | None:
    """The state `kind` moves a piece in `current` to, or None when the table refuses it.
    It does not check the sources: `allowed` does (the duplicate check comes between them)."""
    rule = TRANSITIONS[kind]
    if rule.target == KEEP:
        if current is None:
            return "ready" if kind == "seen" and rule.from_new else None
        return current
    if rule.target == BACK:
        return back_to if back_to not in (None, "review") else "ready"
    if rule.target == STATED:
        return stated(kind, to, back_to)
    return rule.target


def allowed(kind: EventKind, current: State | None) -> bool:
    """May `kind` start from `current` (None: a piece with no history yet)?"""
    rule = TRANSITIONS[kind]
    return rule.from_new if current is None else current in rule.sources


def changes_availability(before: State | None, after: State | None) -> bool:
    """An unverified event that would change this becomes a hold, never a state change (D4.3)."""
    return eligible(before) != eligible(after)


__all__ = [
    "CARD_ONLY",
    "BACK",
    "COUNTED",
    "ELIGIBLE",
    "EVENT_KINDS",
    "HOLDING",
    "KEEP",
    "NEW",
    "STATED",
    "STATED_CHOICES",
    "STATED_DEFAULT",
    "STATES",
    "STATE_SETTING",
    "STATE_WORDS",
    "TRANSITIONS",
    "EventKind",
    "Rule",
    "State",
    "allowed",
    "changes_availability",
    "eligible",
    "owned",
    "stated",
    "target_of",
    "wearable_pair",
    "wearable_set",
]
