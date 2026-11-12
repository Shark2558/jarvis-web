# src/jarvis/documents/pictures.py
"""Attached pictures in the model's window (R11.1; docs/plans/r11-1-observations.md D10; Layer 2).

The Brain calls `with_pictures` on the window it is about to send (both the reply and the stream
path). The pictures kept for the LATEST owner turn (`DocumentService.pictures_of_turn`: cleaned
bytes beside the files sent with that turn, at most `MAX_PICTURES_PER_TURN`) are added to that
turn's message as `ImageBlock`s, and only for a brain whose `BrainSpec.sees_pictures` is true: its
provider reads pictures AND it never learns from what it reads. Every other brain gets one fixed
line per picture (`PICTURE_WITHHELD`) and the bytes are not even read from storage. A picture is
never written into the conversation (`ContentBlock` has no picture) and never sent with a later
turn: the next message's window has none.

`turn_pictures` is the one door for Part D's picture research (`jarvis.picture`): the pictures of
the conversation's latest owner turn, newest first. "Latest" is what `save_owner_turn` recorded
in this process (`DocumentService.note_turn`), so a turn sent before a restart, or a later turn
that came without a picture, gives none. Pass `spec` and a brain that may not see gets none.
Logs carry class names and counts only.
"""

from __future__ import annotations

from pydantic import ValidationError

from jarvis.core.models import Session, Turn
from jarvis.documents.models import StoredPicture
from jarvis.documents.service import DocumentService
from jarvis.llm.base import (
    PICTURE_WITHHELD,
    ChatMessage,
    ImageBlock,
    MessageBlock,
    Role,
    TextBlock,
    without_pictures,
)
from jarvis.llm.brains import BrainSpec
from jarvis.logging import get_logger

log = get_logger(__name__)

MAX_PICTURES_PER_TURN = 4
NOT_LOADED = "[a picture was attached, but it could not be loaded just now]"


def _latest_owner_turn(session: Session) -> Turn | None:
    return next((t for t in reversed(session.turns) if t.role is Role.USER), None)


def _is_turn(message: ChatMessage, turn: Turn) -> bool:
    """Is `message` that turn as the window shows it (its own words first)?"""
    if message.role is not Role.USER:
        return False
    if isinstance(message.content, str):
        return message.content == turn.content
    first = next((b for b in message.content if isinstance(b, TextBlock)), None)
    return first is not None and first.text == turn.content


def _as_blocks(shots: list[StoredPicture]) -> list[ImageBlock]:
    out: list[ImageBlock] = []
    for shot in shots[:MAX_PICTURES_PER_TURN]:
        try:
            out.append(ImageBlock(media_type=shot.media_type, data=shot.data))  # type: ignore[arg-type]
        except ValidationError:  # a stored picture that is not a JPEG / PNG within the size cap
            log.error("stored picture unusable; left out")
    return out


async def _load(
    docs: DocumentService, owner: str, session_id: str, turn_id: str
) -> list[ImageBlock]:
    try:
        return _as_blocks(await docs.pictures_of_turn(owner, session_id, turn_id))
    except Exception as exc:  # noqa: BLE001 — the reply matters more than the picture
        log.warning("attached pictures unreadable", extra={"reason": type(exc).__name__})
        return []


async def with_pictures(
    docs: DocumentService | None, messages: list[ChatMessage], session: Session, spec: BrainSpec
) -> list[ChatMessage]:
    """The window with the latest owner turn's pictures for a brain that may see them, and one
    fixed line per picture for any other. New messages: the caller's list is not changed."""
    turn = _latest_owner_turn(session)
    count = min(sum(a.pictures for a in turn.attachments), MAX_PICTURES_PER_TURN) if turn else 0
    last = messages[-1] if messages else None
    if docs is None or turn is None or last is None or not count or not _is_turn(last, turn):
        return messages if spec.sees_pictures else without_pictures(messages)
    extra: list[MessageBlock]
    if spec.sees_pictures:
        shown = await _load(docs, session.user_id, session.id, turn.id)
        extra = [*shown] if shown else [TextBlock(text=NOT_LOADED)]
    else:
        extra = [TextBlock(text=PICTURE_WITHHELD) for _ in range(count)]
    base: list[MessageBlock] = (
        [TextBlock(text=last.content)] if isinstance(last.content, str) else list(last.content)
    )
    out = [*messages[:-1], ChatMessage(role=last.role, content=[*base, *extra])]
    log.info("pictures with the turn", extra={"count": count, "shown": spec.sees_pictures})
    return out if spec.sees_pictures else without_pictures(out)


async def turn_pictures(
    docs: DocumentService | None,
    user_id: str,
    session_id: str,
    *,
    spec: BrainSpec | None = None,
) -> list[ImageBlock]:
    """The pictures attached to the LATEST owner turn of this conversation, newest first, at most
    `MAX_PICTURES_PER_TURN`; [] when that turn came without one, when it was sent before a
    restart, for anyone but its owner, and (with `spec`) for a brain that may not see pictures.
    Never raises. Part D's picture research calls this; it never reads the store itself."""
    if docs is None or (spec is not None and not spec.sees_pictures):
        return []
    turn_id = docs.picture_turn(user_id, session_id)
    if not turn_id:
        return []
    shown = await _load(docs, user_id, session_id, turn_id)
    return list(reversed(shown))


__all__ = ["MAX_PICTURES_PER_TURN", "NOT_LOADED", "turn_pictures", "with_pictures"]
