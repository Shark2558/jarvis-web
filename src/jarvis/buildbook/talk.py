# src/jarvis/buildbook/talk.py
"""The talk-through: a separate minimal lane (R6 D11, D12; `ports.BookTalker`).

`BookTalk(brains, billing, mode, book, sessions)` holds no `Brain`, gateway, memory, session
store or documents: the brains, billing and the no-AI switch come in through the constructor and
the lane never imports them (tests/test_r6_seams.py pins the package boundary). Per question:

    talk state (Book settings on, AI on, a brain that does not train on what it's told unless
    the owner allows one) -> RESERVE one of this session's questions (a transaction; refused at
    the limit, so parallel asks can't run past it) -> pre-guard -> billing.ensure_allowed ->
    ONE router.complete(tier=BALANCED, system=GUEST_SYSTEM, system_dynamic=fenced digest + canary,
    messages=this session's last 8 turns + the question, max_tokens=400, tools=None) ->
    billing.record -> post-guard (and any tool call refused) -> capped -> stored.

Every refusal is a D13 line and makes NO model call. A refused question is stored as "" (it counts
against the session's questions, but is never sent to a model later). A failed call, No-AI or the
monthly limit answers "ai_off" and gives the reserved question back. A session that closed while
the brain was thinking raises SessionGone (the route answers 401). Nothing here logs a question,
a reply or book text.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol

from jarvis.billing.service import BudgetError
from jarvis.buildbook import digest, guard, prompt
from jarvis.buildbook.lines import LINES
from jarvis.buildbook.model import Book, SessionView, TalkReply, TalkState, canonical_bytes
from jarvis.buildbook.ports import BookSessions, BookSource
from jarvis.llm.base import ChatMessage, Completion, Role
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.router import ModelTier
from jarvis.logging import get_logger

log = get_logger(__name__)

MAX_TOKENS = 400
OFF_SWITCH = "The owner switched questions off in Book settings."
OFF_AI = "No-AI mode is on, so no model is called."
OFF_TRAINING = (
    "Every brain here may learn from what it's told, and the owner hasn't allowed that for the "
    "build book."
)


class Mode(Protocol):
    async def load(self, uid: str) -> str: ...


class Spending(Protocol):
    async def ensure_allowed(self, uid: str, spec: BrainSpec) -> None: ...

    async def record(self, uid: str, brain_id: str, cost_usd: float) -> float: ...


class Prefs(Protocol):
    async def get(self, uid: str) -> Mapping[str, Any]: ...


class Reserving(BookSessions, Protocol):
    """`ports.BookSessions` plus the question reservation of `DocBookSessions`."""

    async def reserve(self, uid: str, session_id: str) -> int | None: ...

    async def release(self, uid: str, session_id: str) -> None: ...

    async def put_turn(self, uid: str, session_id: str, question: str, reply: str) -> int: ...


def request_for(
    book: Book, question: str, turns: Sequence[tuple[str, str]], canary: str
) -> dict[str, Any]:
    """The one call's arguments. `tools` is None always: the lane has no tools to give."""
    chosen = digest.select(
        book.digest, question, budget=prompt.budget_for(book.digest.overview, canary)
    )
    messages: list[ChatMessage] = []
    for asked, said in turns:
        if asked:  # a refused question is stored as "" and never goes to a model
            messages += [
                ChatMessage(role=Role.USER, content=asked),
                ChatMessage(role=Role.ASSISTANT, content=said),
            ]
    messages.append(ChatMessage(role=Role.USER, content=question))
    return {
        "tier": ModelTier.BALANCED,
        "system": prompt.GUEST_SYSTEM,
        "system_dynamic": prompt.reference(book.digest.overview, chosen, canary),
        "messages": messages,
        "max_tokens": MAX_TOKENS,
        "tools": None,
    }


class BookTalk:
    def __init__(
        self,
        brains: BrainRegistry,
        billing: Spending,
        mode: Mode,
        book: BookSource,
        sessions: Reserving,
        *,
        prefs: Prefs | None = None,
        owner_emails: Sequence[str] = (),
        request: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self._brains, self._billing, self._mode = brains, billing, mode
        self._source, self._sessions, self._prefs = book, sessions, prefs
        self._owners = tuple(owner_emails)
        self._request = request or request_for
        self._hosts: tuple[str, frozenset[str]] | None = None  # (release id, hosts)

    async def _pref(self, uid: str, key: str, default: bool) -> bool:
        if self._prefs is None:
            return default
        try:
            value = (await self._prefs.get(uid)).get(key, default)
        except Exception as exc:  # noqa: BLE001 - unreadable: the safe answer for each key
            log.warning("book settings unreadable", extra={"error": type(exc).__name__})
            return default if key == "talk_on" else False
        return value if isinstance(value, bool) else default

    async def _brain(self, uid: str) -> BrainSpec | None:
        default = self._brains.default
        if not default.trains_on_content:
            return default
        private = next((b for b in self._brains.list() if not b.trains_on_content), None)
        if private is not None:
            return private
        return default if await self._pref(uid, "allow_training_brain", False) else None

    async def _ready(self, uid: str) -> tuple[BrainSpec | None, str]:
        if not await self._pref(uid, "talk_on", True):
            return None, OFF_SWITCH
        try:
            mode = await self._mode.load(uid)
        except Exception as exc:  # noqa: BLE001 - can't tell: no model
            log.warning("no-AI switch unreadable", extra={"error": type(exc).__name__})
            mode = "none"
        if mode != "ai":
            return None, OFF_AI
        spec = await self._brain(uid)
        return (spec, "") if spec is not None else (None, OFF_TRAINING)

    async def state(self, uid: str) -> TalkState:
        spec, why = await self._ready(uid)
        return TalkState(on=spec is not None, why=why)

    def _allowed_hosts(self, book: Book) -> frozenset[str]:
        rid = book.release.id
        if self._hosts is None or self._hosts[0] != rid:
            self._hosts = (rid, guard.book_hosts(canonical_bytes(book).decode("utf-8")))
        return self._hosts[1]

    @staticmethod
    def _reply(line_or_text: str, *, refused: bool, left: int) -> TalkReply:
        follow = LINES["anything_else"] if left > 0 else LINES["limit"]
        return TalkReply(
            reply_id=f"r_{secrets.token_hex(6)}",
            reply=line_or_text,
            refused=refused,
            follow_up=follow,
            left=max(0, left),
        )

    async def _call(self, uid: str, spec: BrainSpec, book: Book, request: dict[str, Any]) -> Any:
        """The one model call; None when it could not be made or failed (no question spent)."""
        try:
            await self._billing.ensure_allowed(uid, spec)
        except BudgetError:
            return None
        try:
            done: Completion = await self._brains.router_for(spec.id).complete(**request)
        except Exception as exc:  # noqa: BLE001 - a fixed line, never an error page to a guest
            log.warning("book talk call failed", extra={"error": type(exc).__name__})
            return None
        await self._billing.record(uid, spec.id, done.cost_usd)
        return done

    def _verdict(self, done: Completion, canary: str, book: Book) -> str | None:
        if done.tool_calls:
            return "refuse_action"
        return guard.post_guard(
            done.text,
            canary=canary,
            owner_emails=self._owners,
            allowed_hosts=self._allowed_hosts(book),
        )

    async def ask(self, uid: str, session: SessionView, text: str, *, now: datetime) -> TalkReply:
        sid = session.session_id
        if session.questions_left <= 0:
            return self._reply(LINES["limit"], refused=True, left=0)
        spec, _ = await self._ready(uid)
        if spec is None:
            return self._reply(LINES["ai_off"], refused=True, left=session.questions_left)
        left = await self._sessions.reserve(uid, sid)  # SessionGone: the route answers 401
        if left is None:
            return self._reply(LINES["limit"], refused=True, left=0)
        refusal = guard.pre_guard(text)
        if refusal is not None:
            left = await self._sessions.put_turn(uid, sid, "", LINES[refusal])
            return self._reply(LINES[refusal], refused=True, left=left)
        return await self._answer(uid, spec, sid, text, left)

    async def _give_back(self, uid: str, sid: str, left: int) -> TalkReply:
        await self._sessions.release(uid, sid)
        return self._reply(LINES["ai_off"], refused=True, left=left + 1)

    async def _answer(self, uid: str, spec: BrainSpec, sid: str, text: str, left: int) -> TalkReply:
        try:
            book = self._source.book()
        except Exception as exc:  # noqa: BLE001 - no book: nothing to talk about
            log.warning("book unavailable for a question", extra={"error": type(exc).__name__})
            return await self._give_back(uid, sid, left)
        canary = prompt.new_canary()
        turns = await self._sessions.turns(uid, sid)
        done = await self._call(uid, spec, book, self._request(book, text, turns, canary))
        if done is None:
            return await self._give_back(uid, sid, left)
        verdict = self._verdict(done, canary, book)
        answer = LINES[verdict] if verdict else guard.cap(done.text) or LINES["refuse_meta"]
        left = await self._sessions.put_turn(uid, sid, "" if verdict else text, answer)
        return self._reply(answer, refused=verdict is not None, left=left)


__all__ = ["MAX_TOKENS", "BookTalk", "request_for"]
