# src/jarvis/quota/counter.py
"""What the deployment-wide allowance counters share (Layer 7 via the `Docs` port): web search's
monthly credits (`jarvis.web.allowance`, slice 10 B) and Google's free tiers (`jarvis.quota.ledger`,
slice 12 D2). One counter is one document; these helpers hold the rules both follow:

- a count is a finite whole number ≥ 0 (`whole`); a stored count that isn't makes the counter
  UNREADABLE (`counted` raises the caller's own error) — it is never silently reset to 0;
- a call RESERVES in one transaction (`take`): two callers can't both take the last one, and a
  refusal raised inside writes nothing;
- bookkeeping after a call (a refund, a latch) uses the same transaction but never raises
  (`quietly`): it is logged, and the call's own outcome stands.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from jarvis.logging import get_logger
from jarvis.storage.docs import Docs, DocTx

log = get_logger(__name__)

T = TypeVar("T")
Doc = dict[str, Any]


def whole(v: object) -> bool:
    """A finite whole number ≥ 0 (an int or an integral float; never a bool)."""
    return (
        not isinstance(v, bool)
        and isinstance(v, int | float)
        and math.isfinite(v)
        and v >= 0
        and float(v).is_integer()
    )


def counted(
    doc: object, key: str, *, unreadable: Callable[[str], Exception], what: str
) -> tuple[Mapping[str, Any], int]:
    """(the stored document, its `key` count) — ({}, 0) when there is none yet. Fail closed: a
    document that isn't a mapping, or a count that isn't a whole number, raises
    `unreadable("<what> is not …")`. A missing `key` counts as 0."""
    if doc is None:
        return {}, 0
    if not isinstance(doc, dict):
        raise unreadable(f"{what} is not a document")
    raw = doc.get(key, 0)
    if not whole(raw):
        raise unreadable(f"{what} is not a whole number")
    return doc, int(raw)


def lenient(doc: Mapping[str, Any], key: str) -> int:
    """A count that is only shown, read leniently: 0 when it isn't a whole number."""
    v = doc.get(key, 0)
    return int(v) if whole(v) else 0


async def take(docs: Docs, path: str, step: Callable[[object], tuple[Doc | None, T]]) -> T:
    """Read the counter at `path` and write what `step` makes of it, in ONE transaction. `step`
    gets the stored document (None when there is none) and returns (the document to write, or
    None to write nothing; the answer). It raises to refuse: nothing is written."""

    async def fn(tx: DocTx) -> T:
        new, out = step(await tx.get(path))
        if new is not None:
            tx.set(path, new)
        return out

    return await docs.transaction(fn)


async def quietly(
    docs: Docs,
    path: str,
    step: Callable[[object], Doc | None],
    *,
    event: str,
    extra: Mapping[str, str] | None = None,
) -> None:
    """Bookkeeping after a call (a refund, a latch): `take` that never raises. A failure is
    logged as `event` with the error's class only, never its text."""

    def both(doc: object) -> tuple[Doc | None, None]:
        return step(doc), None

    try:
        await take(docs, path, both)
    except Exception as exc:  # noqa: BLE001 — the call already happened; its outcome stands
        log.warning(event, extra={**(extra or {}), "reason": type(exc).__name__})


__all__ = ["Doc", "counted", "lenient", "quietly", "take", "whole"]
