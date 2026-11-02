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

Outside a turn there is no budget (None): an approval being executed was decided by the owner.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

MAX_NEW_CARDS = 5
MAX_DOC_CALLS = 6

TOO_MANY_CARDS = (
    f"Too many approvals in one request: at most {MAX_NEW_CARDS} new approval cards per message, "
    "so nothing was proposed for this one. Tell the owner what is still to do; they can ask "
    "again in a new message."
)
DOC_LIMIT = (
    f"Document limit for this request reached ({MAX_DOC_CALLS} doc_read / doc_search calls per "
    "message). Answer with what you have; the owner can ask again in a new message."
)


@dataclass
class TurnBudget:
    """Mutable on purpose: one counter object shared by every call of the message."""

    cards: int = MAX_NEW_CARDS
    docs: int = MAX_DOC_CALLS


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


__all__ = [
    "DOC_LIMIT",
    "MAX_DOC_CALLS",
    "MAX_NEW_CARDS",
    "TOO_MANY_CARDS",
    "TurnBudget",
    "current_budget",
    "take_doc_call",
    "turn_budget",
]
