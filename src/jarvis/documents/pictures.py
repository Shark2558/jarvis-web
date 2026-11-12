# src/jarvis/documents/pictures.py
"""Attached pictures in the model's window (R11.1; docs/plans/r11-1-observations.md D10; Layer 2).

The Brain calls `with_pictures` on the window it is about to send. I0: nothing is attached yet,
so the window comes back as it is, minus any picture for a brain that must not see one. Part B
builds the rest here: the pictures stored for the LATEST owner turn (`DocumentService`, kind
`image`, at most `MAX_PICTURES_PER_TURN`) are added to that turn's message as `ImageBlock`s for a
brain whose `sees_pictures` is true; any other brain gets one fixed line per picture instead. A
picture is never written into the conversation and never sent with a later turn.
"""

from __future__ import annotations

from jarvis.core.models import Session
from jarvis.documents.service import DocumentService
from jarvis.llm.base import ChatMessage, ImageBlock, without_pictures
from jarvis.llm.brains import BrainSpec

MAX_PICTURES_PER_TURN = 4


async def with_pictures(
    docs: DocumentService | None, messages: list[ChatMessage], session: Session, spec: BrainSpec
) -> list[ChatMessage]:
    """The window with this turn's pictures, for a brain that may see them (I0: none yet)."""
    del docs, session  # Part B reads the turn's pictures from the document store
    return messages if spec.sees_pictures else without_pictures(messages)


async def turn_pictures(
    docs: DocumentService | None, user_id: str, session_id: str
) -> list[ImageBlock]:
    """The pictures attached to the LATEST owner turn of this conversation, newest first, at most
    `MAX_PICTURES_PER_TURN` (I0: none yet; Part B reads them from the document store). Part D's
    picture research calls this; it never reads the store itself."""
    del docs, user_id, session_id
    return []


__all__ = ["MAX_PICTURES_PER_TURN", "turn_pictures", "with_pictures"]
