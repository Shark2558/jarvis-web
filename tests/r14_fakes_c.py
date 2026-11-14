# tests/r14_fakes_c.py -- R14 Part C's fakes (imported bare: `from r14_fakes_c import ...`; CI
# runs plain pytest from the repository root, which is not on sys.path). Made-up messages only;
# nothing here calls a model, Google or anything that spends.
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from jarvis.llm.base import ChatMessage, Role, ToolCall, ToolResultBlock, ToolSpec
from jarvis.skills.ports import OfferContext

UID = "owner-test"


def specs(*names: str) -> list[ToolSpec]:
    return [
        ToolSpec(name=n, description=f"the {n} tool", input_schema={"type": "object"})
        for n in names
    ]


def owner(text: str) -> ChatMessage:
    return ChatMessage(role=Role.USER, content=text)


def reply(text: str = "Done, Sir.") -> ChatMessage:
    return ChatMessage(role=Role.ASSISTANT, content=text)


def called(name: str, n: int = 0, **args: Any) -> list[ChatMessage]:
    """One tool round as the window replays it: the call, then its result."""
    call = ToolCall(id=f"c{name}{n}", name=name, arguments=dict(args))
    result = ToolResultBlock(tool_use_id=call.id, content="[untrusted tool output]\n{}")
    return [
        ChatMessage(role=Role.ASSISTANT, content=[call]),
        ChatMessage(role=Role.USER, content=[result]),
    ]


def ctx(
    text: str, history: Sequence[ChatMessage] = (), *, uid: str = UID, turn: str = "t1"
) -> OfferContext:
    """The offer's context for `text`, said after `history` (the window ends with his message)."""
    return OfferContext(uid, text, (*history, owner(text)), turn)


def later(
    text: str, rounds: Sequence[ChatMessage], *, uid: str = UID, turn: str = "t1"
) -> OfferContext:
    """A later round of the same turn: his message, then this turn's rounds so far."""
    return OfferContext(uid, text, (owner(text), *rounds), turn)


def names(got: Sequence[ToolSpec]) -> list[str]:
    return [s.name for s in got]


@dataclass
class Clock:
    now: float = 1_000.0

    def __call__(self) -> float:
        return self.now


@dataclass
class Recorder:
    """A `skills.ports.TokenLedger` that keeps what it was given (the brain's record slot)."""

    calls: list[Any] = field(default_factory=list)

    async def record(self, call: Any) -> None:
        self.calls.append(call)


__all__ = [
    "UID", "Clock", "Recorder", "called", "ctx", "later", "names", "owner", "reply", "specs",
]  # fmt: skip
