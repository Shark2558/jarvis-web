# src/jarvis/documents/pictures.py
"""Attached pictures in the model's window (R11.1; docs/plans/r11-1-observations.md D10; Layer 2).

The Brain calls `with_pictures` on the window it is about to send (both the reply and the stream
path). The pictures kept for the LATEST owner turn (`DocumentService.pictures_of_turn`: cleaned
bytes beside the files sent with that turn, at most `MAX_PICTURES_PER_TURN`) are added to that
turn's message as `ImageBlock`s, and only for a brain whose `BrainSpec.sees_pictures` is true: its
provider reads pictures AND it never learns from what it reads. Every other brain gets one fixed
line per picture (`PICTURE_WITHHELD`) and the bytes are not even read from storage. A picture is
never written into the conversation (`ContentBlock` has no picture) and never sent with a later
turn: the next message's window has none. A picture that cannot be loaded is said, never
silently left out ("[1 of the 2 attached pictures could not be loaded just now]").

`turn_pictures` is the one door for Part D's picture research (`jarvis.picture`): the pictures of
the conversation's latest owner turn, newest first. "Latest" is the STORED conversation's latest
owner turn (`DocumentService.sessions`, or the `sessions` passed in), so another instance's newer
turn and a restart are both seen (code review M3); that turn's files are read again through the
document store. It returns a `TurnPictures` (a plain list of `ImageBlock`) whose `unreadable` is
True when the pictures could not be read (storage, a stored picture unusable, no conversation
store): "could not look" is never "no picture". Pass `spec` and a brain that may not see gets
none. Logs carry class names and counts only.
"""

from __future__ import annotations

from collections.abc import Iterable

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
    ToolResultBlock,
    without_pictures,
)
from jarvis.llm.brains import BrainSpec
from jarvis.logging import get_logger
from jarvis.memory.base import SessionStore

log = get_logger(__name__)

MAX_PICTURES_PER_TURN = 4
NOT_LOADED = "[a picture was attached, but it could not be loaded just now]"


class TurnPictures(list[ImageBlock]):
    """The pictures of a turn: a plain list (what Part D was told to rely on), plus `unreadable`:
    True when they could not be read, so the caller can say it could not look."""

    def __init__(self, blocks: Iterable[ImageBlock] = (), *, unreadable: bool = False) -> None:
        super().__init__(blocks)
        self.unreadable = unreadable


def _missing(missing: int, count: int) -> str:
    return f"[{missing} of the {count} attached pictures could not be loaded just now]"


def _owner_wrote(turn: Turn) -> bool:
    """A message the owner sent. The Brain stores each round's tool results as a user turn too
    (blocks only, no words): that is never "his latest message" (R11.1 I1: otherwise a picture
    turn read as "no picture" from its second tool round on, while the brain still saw it)."""
    if turn.role is not Role.USER:
        return False
    return not (turn.blocks and all(isinstance(b, ToolResultBlock) for b in turn.blocks))


def _latest_owner_turn(session: Session) -> Turn | None:
    return next((t for t in reversed(session.turns) if _owner_wrote(t)), None)


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
    docs: DocumentService, owner: str, session_id: str, turn: Turn
) -> tuple[list[ImageBlock], bool]:
    """(the turn's pictures, whether reading them failed)."""
    try:
        return _as_blocks(await docs.pictures_of_turn(owner, session_id, turn)), False
    except Exception as exc:  # noqa: BLE001 — the reply matters more than the picture
        log.warning("attached pictures unreadable", extra={"reason": type(exc).__name__})
        return [], True


def _count(turn: Turn | None) -> int:
    return min(sum(a.pictures for a in turn.attachments), MAX_PICTURES_PER_TURN) if turn else 0


async def with_pictures(
    docs: DocumentService | None, messages: list[ChatMessage], session: Session, spec: BrainSpec
) -> list[ChatMessage]:
    """The window with the latest owner turn's pictures for a brain that may see them, and one
    fixed line per picture for any other. New messages: the caller's list is not changed."""
    turn = _latest_owner_turn(session)
    count = _count(turn)
    last = messages[-1] if messages else None
    if docs is None or turn is None or last is None or not count or not _is_turn(last, turn):
        return messages if spec.sees_pictures else without_pictures(messages)
    extra: list[MessageBlock]
    if spec.sees_pictures:
        shown, _ = await _load(docs, session.user_id, session.id, turn)
        extra = [*shown] if shown else [TextBlock(text=NOT_LOADED)]
        if shown and len(shown) < count:  # code review L6: never silently fewer
            extra.append(TextBlock(text=_missing(count - len(shown), count)))
    else:
        extra = [TextBlock(text=PICTURE_WITHHELD) for _ in range(count)]
    base: list[MessageBlock] = (
        [TextBlock(text=last.content)] if isinstance(last.content, str) else list(last.content)
    )
    out = [*messages[:-1], ChatMessage(role=last.role, content=[*base, *extra])]
    log.info("pictures with the turn", extra={"count": count, "shown": spec.sees_pictures})
    return out if spec.sees_pictures else without_pictures(out)


async def _stored_turn(
    store: SessionStore, user_id: str, session_id: str
) -> tuple[Turn | None, bool]:
    """(the stored conversation's latest owner turn, whether reading it failed); None for a
    conversation that is missing or someone else's."""
    try:
        session = await store.get(session_id)
    except Exception as exc:  # noqa: BLE001 — "could not look", never an error
        log.warning("conversation unreadable for pictures", extra={"reason": type(exc).__name__})
        return None, True
    if session is None or session.user_id != user_id:
        return None, False
    return _latest_owner_turn(session), False


async def turn_pictures(
    docs: DocumentService | None,
    user_id: str,
    session_id: str,
    *,
    spec: BrainSpec | None = None,
    sessions: SessionStore | None = None,
) -> TurnPictures:
    """The pictures attached to the LATEST owner turn of the stored conversation, newest first,
    at most `MAX_PICTURES_PER_TURN`. Empty when that turn came without one, for anyone but its
    owner, and (with `spec`) for a brain that may not see pictures; empty with `unreadable`
    when they could not be read. Never raises. Part D's picture research calls this; it never
    reads the store itself. `sessions` defaults to the document service's own."""
    if docs is None or (spec is not None and not spec.sees_pictures):
        return TurnPictures()
    store = sessions if sessions is not None else docs.sessions
    if store is None:
        log.warning("no conversation store for pictures")
        return TurnPictures(unreadable=True)
    turn, failed = await _stored_turn(store, user_id, session_id)
    count = _count(turn)
    if turn is None or not count:
        return TurnPictures(unreadable=failed)
    shown, failed = await _load(docs, user_id, session_id, turn)
    # fewer than the turn says it came with: some could not be read (code review L6)
    return TurnPictures(reversed(shown), unreadable=failed or len(shown) < count)


__all__ = [
    "MAX_PICTURES_PER_TURN",
    "NOT_LOADED",
    "TurnPictures",
    "turn_pictures",
    "with_pictures",
]
