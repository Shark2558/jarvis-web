# src/jarvis/skills/offer.py
"""The turn's tools (docs/plans/r14-hardening.md D9): send the model only the tools a message
needs; any other on request (`skills_open`).

`SkillOffer` is `skills.ports.ToolOffer`, the brain's tool slot (bound only while `tool_offer` is
"by_skill"; "all" is the kill switch and `offer_all` is what the slot does without it). A turn's
set, built at its first model call and then fixed, is the union of
- the groups whose words (the register's, English and his common Hinglish) are in his message;
- the groups of every tool used in the last `HISTORY_TURNS` turns;
- the previous turn's set, while it is under `tool_offer_sticky_s` old (so the cache still hits)
  and not over `STICKY_MAX_TOOLS`;
- the register's core (`skills_open`, `reminder_add`, `calendar_list_events`, `memory_search`);
- every tool a tool_use block in the window names (a replayed call never names a tool the
  provider wasn't offered).
Within the turn the only change: after the model calls `skills_open(skill)`, the next round adds
that skill's tools. A tool the register can't file (unknown, or filed twice) is always offered.
The offer only narrows what the model sees: every call still passes `jarvis.tools.gateway` and
meets its registry, permission rows, Telegram classes, taint rules and R3 tokens.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from jarvis.llm.base import ChatMessage, Role, ToolCall, ToolResultBlock
from jarvis.skills.ids import SKILL_IDS, SkillId
from jarvis.skills.registry import SkillRegister

if TYPE_CHECKING:
    from jarvis.llm.base import ToolSpec
    from jarvis.skills.ports import OfferContext

HISTORY_TURNS: Final = 3
STICKY_MAX_TOOLS: Final = 40  # a sticky set past this starts afresh (a long busy session)
SHORT_WORD: Final = 3  # words this short match a whole word, or with an s ("ac", "tv", "emi")
OPEN_TOOL: Final = "skills_open"
_EDGE = r"(?<![a-z0-9])"


def offer_all(ctx: OfferContext | None, specs: Sequence[ToolSpec]) -> list[ToolSpec]:
    return list(specs)


def _word_pattern(word: str) -> str:
    body = r"\s+".join(re.escape(part) for part in word.split())
    tail = r"s?(?![a-z0-9])" if len(word) <= SHORT_WORD else ""  # "emi" and "emis", never "email"
    return _EDGE + body + tail


class Words:
    """One group's words: each matches at the start of a word, case-insensitively."""

    def __init__(self, entries: Iterable[str]) -> None:
        alts = [_word_pattern(w) for w in entries]
        self._re = re.compile("|".join(alts)) if alts else None

    def search(self, text: str) -> bool:
        if self._re is None:
            return False
        return self._re.search(text.lower().replace("’", "'")) is not None


@dataclass(frozen=True)
class _Turn:
    key: tuple[str, int, str]
    groups: frozenset[str]
    at: float


def _owner_message(m: ChatMessage) -> bool:
    if m.role is not Role.USER:
        return False
    return isinstance(m.content, str) or not any(isinstance(b, ToolResultBlock) for b in m.content)


def turns_of(messages: Sequence[ChatMessage]) -> list[list[ChatMessage]]:
    """The window cut into turns, each starting at one of his messages (a tool result is not)."""
    out: list[list[ChatMessage]] = []
    for m in messages:
        if _owner_message(m) or not out:
            out.append([m])
        else:
            out[-1].append(m)
    return out


def calls_in(messages: Iterable[ChatMessage]) -> list[ToolCall]:
    return [
        b
        for m in messages
        if m.role is Role.ASSISTANT and not isinstance(m.content, str)
        for b in m.content
        if isinstance(b, ToolCall)
    ]


def opened_skills(messages: Iterable[ChatMessage]) -> frozenset[SkillId]:
    """The skills `skills_open` calls among `messages` asked for (an unknown one: none)."""
    asked = {c.arguments.get("skill") for c in calls_in(messages) if c.name == OPEN_TOOL}
    return frozenset(s for s in SKILL_IDS if s in asked)


class SkillOffer:
    def __init__(
        self,
        register: SkillRegister,
        *,
        sticky_s: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._reg = register
        self._words = {g.id: Words(g.words) for g in register.catalogue.groups}
        self._core = frozenset(register.catalogue.core)
        self._sticky_s = sticky_s
        self._clock = clock
        self._last: dict[str, _Turn] = {}  # per owner: the current (or last) turn's set

    def __call__(self, ctx: OfferContext, specs: Sequence[ToolSpec]) -> list[ToolSpec]:
        turns = turns_of(ctx.messages)
        opened = opened_skills(turns[-1]) if turns else frozenset()
        groups = self._turn_groups(ctx, turns, specs, opened)
        named = {c.name for c in calls_in(ctx.messages)}
        return [s for s in specs if self._offered(s.name, groups, named)]

    def _offered(self, name: str, groups: frozenset[str], named: set[str]) -> bool:
        filed = self._reg.filed(name)
        if len(filed) != 1:
            return True  # unknown or filed twice: never hide it
        return name in self._core or name in named or filed[0].id in groups

    def _turn_groups(
        self,
        ctx: OfferContext,
        turns: list[list[ChatMessage]],
        specs: Sequence[ToolSpec],
        opened: frozenset[SkillId],
    ) -> frozenset[str]:
        now, key = self._clock(), (ctx.turn, len(turns), ctx.text)
        last = self._last.get(ctx.uid)
        if last is not None and last.key == key:
            groups = last.groups  # fixed for the whole turn
        else:
            groups = self._fresh(ctx.text, turns)
            if last is not None and now - last.at < self._sticky_s:
                union = groups | last.groups
                if self._count(union, specs) <= STICKY_MAX_TOOLS:
                    groups = union
        groups |= {g.id for g in self._reg.catalogue.groups if g.skill in opened}
        self._last[ctx.uid] = _Turn(key, groups, now)
        return groups

    def _fresh(self, text: str, turns: list[list[ChatMessage]]) -> frozenset[str]:
        hits = {gid for gid, words in self._words.items() if words.search(text)}
        for turn in turns[-HISTORY_TURNS:]:
            for call in calls_in(turn):
                group = self._reg.group_of(call.name)
                if group is not None:
                    hits.add(group.id)
        return frozenset(hits)

    def _count(self, groups: frozenset[str], specs: Sequence[ToolSpec]) -> int:
        return sum(1 for s in specs if (g := self._reg.group_of(s.name)) and g.id in groups)


__all__ = [
    "HISTORY_TURNS",
    "OPEN_TOOL",
    "STICKY_MAX_TOOLS",
    "SkillOffer",
    "Words",
    "calls_in",
    "offer_all",
    "opened_skills",
    "turns_of",
]
