# src/jarvis/tools/budget.py
"""What one owner message may still do with tools (slice 10 integration review L4 / L5; Layer 4).

The Brain opens `turn_budget()` around one owner message's tool loop (every round of it). Tools
and the gateway read it with `current_budget()`:

- `cards`: new approval cards the message may still propose (5). A model told by a page or a
  file to "do this for all 50 contacts" can't flood the owner's Approvals list; a proposal past
  the budget is refused with a plain "too many approvals in one request" — nothing is stored. A
  proposal identical to a card already waiting is not a new card and costs nothing.
- `docs`: doc_read / doc_search calls the message may still make (6), like web search's
  per-message caps — each reply's document reading stays bounded, and one message's documents
  always fit the attachment cache together (`documents.store.CACHE_DOCS`).
- `deletes` (slice 11 D3): undo-able deletes (`Tool.undoable`) the message may still run without
  a card (10). From the 11th each such delete becomes an R2 approval card — so `cards` then
  bounds them too — and the model is told why in plain words (`DELETES_CAPPED`).
- `maps` / `youtube_searches` (slice 12 D2): Google Maps calls (3) and YouTube searches (2) the
  message may still make — Google's free allowances are the whole deployment's, so a page that
  says "look up 50 places" can't spend them.

Outside a turn there is no budget (None): an approval being executed was decided by the owner.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

MAX_NEW_CARDS = 5
MAX_DOC_CALLS = 6
MAX_FREE_DELETES = 10
MAX_MAPS_CALLS = 3
MAX_YOUTUBE_SEARCHES = 2

DELETES_CAPPED = (
    f"More than {MAX_FREE_DELETES} deletes in one request: the first {MAX_FREE_DELETES} ran, and "
    "from then on each delete waits for the owner's approval (at most "
    f"{MAX_NEW_CARDS} new approvals per message). Tell the owner which deletes are waiting."
)

TOO_MANY_CARDS = (
    f"Too many approvals in one request: at most {MAX_NEW_CARDS} new approval cards per message, "
    "so nothing was proposed for this one. Tell the owner what is still to do; they can ask "
    "again in a new message."
)
DOC_LIMIT = (
    f"Document limit for this request reached ({MAX_DOC_CALLS} doc_read / doc_search calls per "
    "message). Answer with what you have; the owner can ask again in a new message."
)
MAPS_LIMIT = (
    f"Maps limit for this request reached ({MAX_MAPS_CALLS} Maps look-ups per message). Answer "
    "with what you have; the owner can ask again in a new message."
)
YOUTUBE_LIMIT = (
    f"YouTube search limit for this request reached ({MAX_YOUTUBE_SEARCHES} searches per "
    "message). Answer with what you have; the owner can ask again in a new message."
)


@dataclass
class TurnBudget:
    """Mutable on purpose: one counter object shared by every call of the message."""

    cards: int = MAX_NEW_CARDS
    docs: int = MAX_DOC_CALLS
    deletes: int = MAX_FREE_DELETES
    maps: int = MAX_MAPS_CALLS
    youtube_searches: int = MAX_YOUTUBE_SEARCHES


_current: contextvars.ContextVar[TurnBudget | None] = contextvars.ContextVar(
    "jarvis_turn_budget", default=None
)


def current_budget() -> TurnBudget | None:
    """This owner message's budget, or None outside a turn."""
    return _current.get()


@contextmanager
def turn_budget() -> Iterator[TurnBudget]:
    """A fresh budget for one owner message (always reset afterwards)."""
    budget = TurnBudget()
    token = _current.set(budget)
    try:
        yield budget
    finally:
        _current.reset(token)


def take_doc_call() -> None:
    """Count one document call against the message's budget; raises (plain words) past it."""
    budget = _current.get()
    if budget is None:
        return
    if budget.docs <= 0:
        raise RuntimeError(DOC_LIMIT)
    budget.docs -= 1


def take_maps_call() -> None:
    """Count one Google Maps call; raises (plain words) past the message's allowance."""
    budget = _current.get()
    if budget is None:
        return
    if budget.maps <= 0:
        raise RuntimeError(MAPS_LIMIT)
    budget.maps -= 1


def take_youtube_search() -> None:
    """Count one YouTube search; raises (plain words) past the message's allowance."""
    budget = _current.get()
    if budget is None:
        return
    if budget.youtube_searches <= 0:
        raise RuntimeError(YOUTUBE_LIMIT)
    budget.youtube_searches -= 1


def take_free_delete() -> bool:
    """Count one undo-able delete that would run without a card. False once the message has used
    its allowance: the caller turns the delete into an approval card. No turn: no cap."""
    budget = _current.get()
    if budget is None:
        return True
    if budget.deletes <= 0:
        return False
    budget.deletes -= 1
    return True


__all__ = [
    "DELETES_CAPPED",
    "DOC_LIMIT",
    "MAPS_LIMIT",
    "MAX_DOC_CALLS",
    "MAX_FREE_DELETES",
    "MAX_MAPS_CALLS",
    "MAX_NEW_CARDS",
    "MAX_YOUTUBE_SEARCHES",
    "TOO_MANY_CARDS",
    "YOUTUBE_LIMIT",
    "TurnBudget",
    "current_budget",
    "take_doc_call",
    "take_free_delete",
    "take_maps_call",
    "take_youtube_search",
    "turn_budget",
]
