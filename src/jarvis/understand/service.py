# src/jarvis/understand/service.py
""" "Heard / understood as" (R11.1; plan D8, D9, D21-B; Layer 2 input processing).

A spoken message goes through this one step before the Brain:

    1. the fixed rules, free (`rules.apply`): known mishearings and near-matches against the
       per-turn hints. Sure -> done, no model.
    2. a protected word (a number, a date, a time, a name, an address) stopped the only fix ->
       the one question, at once; the model is not asked to do what the rules may not (D21-B).
    3. unsure (a word that is no word, a near-miss with two candidates, or the recogniser's own
       low confidence) and the AI is on -> ONE fast-tier call (`model.FastCheck`), admitted and
       metered; its answer is used only if `guard.acceptable` passes it.
    4. still unsure -> one short question instead of acting. Low confidence alone never asks:
       with no model to check it, the words go through as heard.

The answer is `{understood, changed, sure, question, via}`. The console shows "Heard / Understood
as" when something changed and sends the understood text on `channel: voice` with `heard` beside
it (display only: `Turn.heard` is never in a model's window and never learned from). With
`voice_understand` off the step answers "as heard" (`via: off`).

Hints (D9) come from here too, for the cloud recogniser and the browser's: the names of the
owner's files waiting to be sent and attached in this conversation, and his own turns' nouns.
Logs carry class names and counts only: never a heard word, a file name or a question.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from jarvis.api.ratelimit import RateLimiter
from jarvis.documents.note import clean_name
from jarvis.fixes.ports import FixContext
from jarvis.llm.base import Role
from jarvis.logging import get_logger
from jarvis.understand import rules
from jarvis.understand.guard import acceptable
from jarvis.understand.hints import file_hints, turn_hints
from jarvis.understand.model import FastCheck

log = get_logger(__name__)

Via = Literal["rules", "ai", "none", "off"]
HEARD_LIMIT = 2_000
MAX_ALTERNATIVES = 3
MAX_FILES = 20
LOW_CONFIDENCE = 0.6  # the recogniser's own doubt, when it says
UNDERSTAND_PER_MINUTE = 60
QUOTE_CHARS = 160


@dataclass(frozen=True)
class Understood:
    understood: str
    changed: bool
    sure: bool
    question: str | None = None
    via: Via = "rules"


@dataclass(frozen=True)
class TurnHints:
    turn: tuple[str, ...]  # files and the conversation's nouns (what the recognisers get)
    all: tuple[str, ...]  # those plus the owner's own "Words to recognise" (what the rules use)
    files: dict[str, str]  # a file hint, casefolded -> that file's name


def _same(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


class UnderstandService:
    def __init__(self, ctx: FixContext, *, model: FastCheck | None = None) -> None:
        self._ctx = ctx
        self._model = model or FastCheck(ctx)
        self._limiter = RateLimiter(UNDERSTAND_PER_MINUTE)

    @property
    def enabled(self) -> bool:
        return bool(self._ctx.s.voice_understand)

    def reset_limits(self) -> None:
        self._limiter = RateLimiter(UNDERSTAND_PER_MINUTE)

    def allow(self, uid: str) -> tuple[bool, float]:
        return self._limiter.allow(uid)

    # ---- hints (D9) --------------------------------------------------------------------------

    async def _file_names(
        self, uid: str, given: Sequence[str], session_id: str | None
    ) -> list[str]:
        names = [clean_name(n) for n in list(given)[:MAX_FILES] if isinstance(n, str)]
        docs = self._ctx.state("documents")
        if docs is None:
            return [n for n in names if n]
        try:
            waiting = [a for a in await docs.store.waiting() if a.owner == uid]
            here = await docs.store.in_session(session_id) if session_id else []
            mine = [*waiting, *(a for a in here if a.owner == uid)]
            names += [a.name for a in sorted(mine, key=lambda a: a.created_at, reverse=True)]
        except Exception as exc:  # noqa: BLE001 — hints are a help, never a reason to fail
            log.warning("file names unreadable for hints", extra={"error": type(exc).__name__})
        return [n for n in names if n][: 2 * MAX_FILES]

    async def _owner_messages(self, uid: str, session_id: str | None) -> list[str]:
        store = self._ctx.state("store")
        if store is None or not session_id:
            return []
        try:
            session = await store.get(session_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("conversation unreadable for hints", extra={"error": type(exc).__name__})
            return []
        if session is None or session.user_id != uid:
            return []
        return [t.content for t in session.turns if t.role is Role.USER and t.content]

    async def _own_words(self, uid: str) -> tuple[str, ...]:
        voice = self._ctx.state("voice")
        if voice is None:
            return ()
        return tuple((await voice.settings_of(uid)).phrases)  # never raises

    async def hints(
        self, uid: str, *, files: Sequence[str] = (), session_id: str | None = None
    ) -> TurnHints:
        names = await self._file_names(uid, files, session_id)
        said = await self._owner_messages(uid, session_id)
        turn = turn_hints(names, said, limit=int(self._ctx.s.voice_hint_words))
        by_hint: dict[str, str] = {}
        for name in names:
            for hint in file_hints([name])[:1]:
                by_hint.setdefault(hint.casefold(), name)
        return TurnHints(turn=turn, all=(*turn, *await self._own_words(uid)), files=by_hint)

    # ---- the step ----------------------------------------------------------------------------

    def _question(self, heard: str, out: rules.Outcome, files: dict[str, str]) -> str:
        sir = self._ctx.s.user_honorific
        if out.candidate is not None:
            return f"Did you mean “{out.candidate}”, {sir}?"
        if out.near:
            name = next((files[h.casefold()] for h in out.near if h.casefold() in files), None)
            if name is not None:
                return f"Did you mean the file {name}, {sir}?"
            return f"Did you mean “{out.near[0]}”, {sir}?"
        shown = heard if len(heard) <= QUOTE_CHARS else heard[: QUOTE_CHARS - 1] + "…"
        return f"I heard “{shown}”, {sir}. Could you say that again?"

    async def understand(
        self,
        uid: str,
        heard: str,
        *,
        alternatives: Sequence[str] = (),
        files: Sequence[str] = (),
        session_id: str | None = None,
        confidence: float | None = None,
    ) -> Understood:
        heard = " ".join(heard.split())[:HEARD_LIMIT]
        if not self.enabled or not heard:
            return Understood(heard, False, True, None, "off")
        hints = await self.hints(uid, files=files, session_id=session_id)
        out = rules.apply(heard, hints.all)
        result = await self._decide(uid, heard, out, hints, alternatives, confidence)
        log.info(
            "understood-as",
            extra={"via": result.via, "changed": result.changed, "sure": result.sure},
        )
        return result

    async def _decide(
        self,
        uid: str,
        heard: str,
        out: rules.Outcome,
        hints: TurnHints,
        alternatives: Sequence[str],
        confidence: float | None,
    ) -> Understood:
        if out.candidate is not None:  # D21-B: the only fix touches a protected word: ask
            return Understood(heard, False, False, self._question(heard, out, hints.files))
        doubtful = confidence is not None and confidence < LOW_CONFIDENCE
        if out.sure and not doubtful:
            return Understood(out.text, out.changed, True)
        others = [" ".join(a.split())[:HEARD_LIMIT] for a in list(alternatives)[:MAX_ALTERNATIVES]]
        answer = await self._model.ask(
            uid, heard=heard, text=out.text, alternatives=others, hints=hints.all
        )
        if (
            answer is not None
            and answer.sure
            and acceptable(heard, answer.understood, alternatives=others, hints=hints.all)
        ):
            return Understood(
                answer.understood, not _same(answer.understood, heard), True, None, "ai"
            )
        if out.sure and answer is None:  # only the recogniser's doubt, and no model to ask
            return Understood(out.text, out.changed, True)
        via: Via = "none" if answer is None else "ai"
        return Understood(heard, False, False, self._question(heard, out, hints.files), via)


__all__ = [
    "HEARD_LIMIT",
    "LOW_CONFIDENCE",
    "UNDERSTAND_PER_MINUTE",
    "TurnHints",
    "Understood",
    "UnderstandService",
]
