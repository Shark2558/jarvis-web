# src/jarvis/tools/undo_delete.py
"""Keeping a copy, then deleting (slice 11 fix; Layer 5/6) — the steps the event and to-do
deletes share.

keep_copy           the copy goes into Recently deleted with where the delete came from (the
                    conversation and the request's trace id). No copy → nothing is deleted.
delete_after_keep   the delete itself. When Google's answer is lost (`GoogleUncertain`: no
                    answer, a 5xx) the item is read again before anything is decided:
                      gone (404 / 410 / cancelled / deleted)  → done; the copy stays
                      still there                              → not deleted; the copy goes
                      the read fails too                       → "unconfirmed"; the copy STAYS
                    An orphan copy is better than lost data: a restore checks that the
                    original is really gone before it makes anything.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from jarvis.integrations.google import GoogleUncertain
from jarvis.logging import get_logger, get_trace_id
from jarvis.tools.context import ToolContext
from jarvis.undo.models import DeletedItem, Kind
from jarvis.undo.service import UndoBin

log = get_logger(__name__)

NO_TRACE = "-"


async def keep_copy(
    undo: UndoBin,
    ctx: ToolContext,
    kind: Kind,
    title: str,
    snapshot: dict[str, Any],
    *,
    owner_authored: bool,
) -> DeletedItem:
    trace = get_trace_id()
    return await undo.keep(
        ctx.user_id,
        kind,
        title,
        snapshot,
        owner_authored=owner_authored,
        session_id=ctx.session_id,
        trace_id=None if trace == NO_TRACE else trace,
    )


async def delete_after_keep(
    undo: UndoBin,
    uid: str,
    item_id: str,
    delete: Callable[[], Awaitable[Any]],
    gone: Callable[[], Awaitable[bool]],
) -> bool:
    """True: deleted (or found gone). False: unconfirmed — the copy stays. Raises (after
    dropping the copy) when the item was NOT deleted."""
    try:
        await delete()
        return True
    except GoogleUncertain:
        verdict = await _checked(gone)
        if verdict is None:
            return False
        if verdict:
            return True
        await undo.discard(uid, item_id)  # still there: no "undo" for a delete that didn't happen
        raise
    except Exception:
        await undo.discard(uid, item_id)
        raise


async def _checked(gone: Callable[[], Awaitable[bool]]) -> bool | None:
    try:
        return await gone()
    except Exception as exc:  # noqa: BLE001 — can't tell: keep the copy, say so
        log.warning("delete could not be checked; copy kept", extra={"error": type(exc).__name__})
        return None


__all__ = ["delete_after_keep", "keep_copy"]
