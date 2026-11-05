# src/jarvis/core/channel.py
"""Which surface a turn is on, and whether the fallback brain answered it (R1 I0 seam).

Per-request context, like `jarvis.tools.taint`: the Telegram service wraps a turn in
`telegram_turn()` so policy (`telegram.rules.ChannelRules`) can tell the call came from Telegram;
the Brain calls `reset_offline()` at the start of a turn and the fallback brain calls
`mark_offline()` when it answers, so `offline.rules.OfflineRules` can ask on every write of that
turn. The offline flag lives in a small mutable holder so a mark made in a child task (a
streamed reply, a gathered call) is still seen by the request that reset it.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager

_telegram: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "jarvis_on_telegram", default=False
)
_offline: contextvars.ContextVar[list[bool] | None] = contextvars.ContextVar(
    "jarvis_answered_offline", default=None
)


@contextmanager
def telegram_turn() -> Iterator[None]:
    """Everything decided inside is on the owner's Telegram conversation."""
    token = _telegram.set(True)
    try:
        yield
    finally:
        _telegram.reset(token)


def on_telegram() -> bool:
    return _telegram.get()


def reset_offline() -> None:
    """A new request: nothing has been answered offline yet."""
    _offline.set([False])


def mark_offline() -> None:
    """The fallback brain answered a model call of this request."""
    holder = _offline.get()
    if holder is None:
        _offline.set([True])
    else:
        holder[0] = True


def answered_offline() -> bool:
    holder = _offline.get()
    return holder is not None and holder[0]


__all__ = ["answered_offline", "mark_offline", "on_telegram", "reset_offline", "telegram_turn"]
