# src/jarvis/core/saving.py
"""Saving a turn when another window may have changed the conversation (slice 10, Layer 3).

The session store refuses to overwrite a conversation that another process changed first
(`SessionConflict`, jarvis.storage.sessions). What the Brain does about it depends on the save:

- The owner's new message (`save_owner_message`): nothing of the turn is stored and no model
  has been called, so the conflict becomes `MessageNotSaved` (409: send it again).
- A later save of the same turn: the message is already stored, only the reply is lost
  (409: your message was kept).
- After an approved or declined action (`record_after_action`): the decision has already taken
  effect, so this never raises — raising would make the owner try again and e.g. send twice.
  The conversation is reloaded and the decision's turns re-appended once; if even that fails,
  the caller says in the reply that the action was not recorded (`not_recorded_note`).
"""

from __future__ import annotations

from collections.abc import Sequence

from jarvis.core.models import Session, Turn
from jarvis.logging import get_logger
from jarvis.memory.base import MessageNotSaved, SessionConflict, SessionStore

log = get_logger(__name__)


async def save_owner_message(store: SessionStore, session: Session) -> None:
    try:
        await store.save(session)
    except MessageNotSaved:
        raise
    except SessionConflict as exc:
        raise MessageNotSaved(str(exc)) from exc


async def _reapply(store: SessionStore, session: Session, turns: Sequence[Turn]) -> Session | None:
    fresh = await store.get(session.id)
    if fresh is None:  # deleted in another window: the record has nowhere to go
        return None
    have = {t.id for t in fresh.turns}
    for t in turns:
        if t.id not in have:
            fresh.append(t)
    await store.save(fresh)  # a second conflict is the caller's to report
    return fresh


async def record_after_action(
    store: SessionStore, session: Session, turns: Sequence[Turn]
) -> tuple[Session, bool]:
    """Store `session`, whose last `turns` were just appended. Returns the session to continue
    with (the reloaded one after a re-apply) and whether the turns are stored. Never raises."""
    try:
        await store.save(session)
        return session, True
    except SessionConflict:
        log.warning("conversation changed during a decision; re-recording on the newer one",
                    extra={"session_id": session.id})  # fmt: skip
    except Exception as exc:  # noqa: BLE001 — the decision stands; the reply says so
        log.error("SAVE FAILED after an owner decision; reply still sent",
                  extra={"session_id": session.id, "error": type(exc).__name__})  # fmt: skip
        return session, False
    try:
        fresh = await _reapply(store, session, turns)
    except Exception as exc:  # noqa: BLE001
        log.error("decision not recorded after a reload",
                  extra={"session_id": session.id, "error": type(exc).__name__})  # fmt: skip
        return session, False
    return (fresh, True) if fresh is not None else (session, False)


def not_recorded_note(approved: bool) -> str:
    """Added to the reply when the decision's record could not be stored."""
    what = "It was done" if approved else "Nothing was done"
    return (
        f"({what}, but this conversation changed in another window, so I could not record"
        " it here. Reload the conversation to see the latest.)"
    )


__all__ = ["not_recorded_note", "record_after_action", "save_owner_message"]
