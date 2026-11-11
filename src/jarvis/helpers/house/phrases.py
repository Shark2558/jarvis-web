# src/jarvis/helpers/house/phrases.py
"""Part B's No-AI phrases (docs/plans/r11-free-helpers.md D18): tried before every older pattern,
so each is anchored to the whole sentence and uses Part B's own words only (chore, upkeep or
maintenance, weather, disaster / weather alerts or warnings, breach notices). Marking something
done needs the word "chore" or "upkeep", so "mark the report done" is never taken. Each ends in
one of Part B's own tools, through the gateway like any tool call. No model.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime

from jarvis.offline.rules import NoAICall, NoAIRoute

_I = re.IGNORECASE
_LEAD = r"^\s*(?:jarvis[,\s]+)?(?:please\s+)?"
_END = r"\s*[?.!]*\s*$"
_ASK = (
    r"(?:(?:show|list|read|check|tell)\s+(?:me\s+)?|what(?:'s|\s+is|\s+are)?\s+|any\s+"
    r"|are\s+there\s+(?:any\s+)?)?"
)
_THE = r"(?:(?:the|my)\s+)?"
_LABEL = r"(?P<label>[A-Za-z][\w' -]{0,38}?)"

CHORES = re.compile(
    _LEAD + _ASK + _THE + r"(?:chores?(?:\s+rota)?|chore\s+list)"
    r"(?:\s+(?:due\s+)?(?:for\s+)?today)?" + _END,
    _I,
)
CHORE_DONE = re.compile(
    _LEAD
    + r"(?:(?:mark|tick\s+off)\s+"
    + _THE
    + _LABEL
    + r"\s+chore(?:\s+as)?\s+done|"
    + r"(?:i(?:'ve|\s+have)?\s+)?(?:did|done|finished)\s+"
    + _THE
    + r"(?P<label2>[A-Za-z][\w' -]{0,38}?)\s+chore|"
    + _THE
    + r"(?P<label3>[A-Za-z][\w' -]{0,38}?)\s+chore\s+(?:is\s+)?done)"
    + _END,
    _I,
)
UPKEEP = re.compile(
    _LEAD + _ASK + _THE + r"(?:home\s+)?(?:upkeep|maintenance)(?:\s+(?:list|schedule))?"
    r"(?:\s+(?:is\s+|are\s+)?due(?:\s+soon)?)?" + _END,
    _I,
)
UPKEEP_DONE = re.compile(
    _LEAD + r"(?:mark|tick\s+off)\s+" + _THE + _LABEL
    + r"\s+(?:upkeep|maintenance)(?:\s+as)?\s+done" + _END,
    _I,
)  # fmt: skip
WEATHER = re.compile(
    _LEAD + r"(?:(?:what(?:'s|\s+is)|how(?:'s|\s+is))\s+the\s+)?weather"
    r"(?:\s+(?:today|now|like(?:\s+today)?|forecast))?" + _END,
    _I,
)
DISASTER = re.compile(
    _LEAD + _ASK + _THE + r"(?:disaster|weather|sachet|flood|cyclone)\s+(?:alerts?|warnings?)"
    r"(?:\s+(?:today|now|for\s+my\s+(?:area|district)))?" + _END,
    _I,
)
BREACH = re.compile(
    _LEAD + _ASK + _THE + r"(?:data\s+)?breach\s+(?:notices?|alerts?|warnings?)" + _END, _I
)

Router = Callable[[str, datetime], NoAIRoute | None]


def _one(tool: str, **args: str) -> NoAIRoute:
    return NoAIRoute((NoAICall(tool, dict(args)),))


def _fixed(pattern: re.Pattern[str], tool: str) -> Router:
    def route(text: str, now: datetime) -> NoAIRoute | None:
        return _one(tool) if pattern.match(text) else None

    return route


def chore_done(text: str, now: datetime) -> NoAIRoute | None:
    m = CHORE_DONE.match(text)
    if m is None:
        return None
    label = next(g for g in (m.group("label"), m.group("label2"), m.group("label3")) if g)
    return _one("chore_done", chore=" ".join(label.split()))


def upkeep_done(text: str, now: datetime) -> NoAIRoute | None:
    m = UPKEEP_DONE.match(text)
    return _one("maint_done", item=" ".join(m.group("label").split())) if m else None


PHRASES: tuple[Router, ...] = (
    chore_done,
    upkeep_done,
    _fixed(CHORES, "chore_list"),
    _fixed(UPKEEP, "maint_list"),
    _fixed(DISASTER, "disaster_status"),
    _fixed(WEATHER, "weather_now"),
    _fixed(BREACH, "breach_status"),
)

__all__ = ["PHRASES", "chore_done", "upkeep_done"]
