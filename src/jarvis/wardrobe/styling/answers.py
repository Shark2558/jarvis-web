# src/jarvis/wardrobe/styling/answers.py
"""R13 Part C's tools' shared steps (D10, D18): who is asking (the tool context's owner, never an
argument), whether C can answer now (off, his wardrobe not ready, his plans unreadable), and a
refusal in plain words. Every word here is fixed."""

from __future__ import annotations

from typing import Any

from jarvis.tools.context import current_tool_context, require_tool_context
from jarvis.wardrobe.model import WardrobeView
from jarvis.wardrobe.styling import texts
from jarvis.wardrobe.styling.plans import StylingDoc
from jarvis.wardrobe.styling.sealed import Unreadable
from jarvis.wardrobe.styling.service import Here, Styling

Ready = tuple[str, Here, StylingDoc, WardrobeView]


def uid() -> str:
    return require_tool_context().user_id


def refused(message: str) -> dict[str, Any]:
    return {"refused": True, "message": message}


def via() -> str:
    ctx = current_tool_context()
    return "voice" if ctx is not None and ctx.spoken else "chat"


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


async def ready(s: Styling) -> Ready | dict[str, Any]:
    """(his uid, where and when, his plans, his wardrobe), or a refusal in fixed words."""
    if (off := s.off()) is not None:
        return refused(off)
    who = uid()
    view = await s.view(who)
    if view is None:
        return refused(texts.NOT_READY_YET)
    try:
        doc = await s.plans.read(who)
    except Unreadable:  # a key change: said in words, never a bare failure (security M3)
        return refused(texts.UNREADABLE)
    return who, await s.where(who), doc, view


__all__ = ["Ready", "plural", "ready", "refused", "uid", "via"]
