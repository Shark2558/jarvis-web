# src/jarvis/series/phrases.py
"""The plans' No-AI phrases (R11.1 O2b; docs/plans/r11-1-observations.md D6; R11 D18's
phrasebook, `BrainMode.add_phrases`). `route(text, now)` answers the check-in with no model:

    "session done", "session 7 is done", "the session happened", "I did the session"
    "session skipped", "session 12 skipped", "I skipped the session", "the session didn't
    happen", "skip session 3"
    "show my plans", "how is my study plan going?"
    "re-plan my sessions", "move my skipped session"

It only CHOOSES a tool call; the call still goes through the gateway (the owner's rows, the
card for moving sessions). A sentence that merely mentions a session is left to the others.
"""

from __future__ import annotations

import re
from datetime import datetime

from jarvis.offline.rules import NoAICall, NoAIRoute
from jarvis.series.tools import CHECKIN, LIST, RESCHEDULE

_I = re.IGNORECASE
_LEAD = r"^\s*(?:(?:hey\s+)?jarvis[,\s]+)?(?:please\s+)?"
_END = r"\s*[.!]*\s*$"
_THE = r"(?:(?:the|my|that|this|today'?s|tonight'?s)\s+)?"
_NUM = r"(?:\s+(?:number\s+)?(\d{1,3}))?"
_DONE = r"(?:done|finished|completed|complete|happened|went\s+ahead|over)"
_SKIP = (
    r"(?:skipped|missed|cancelled|canceled|did\s*n[o']?t\s+happen|did\s+not\s+happen|not\s+done)"
)
_BE = r"(?:\s+(?:is|was|has|got))?"
# "session [7] [is] done" / "session [7] [was] skipped"
_SESSION_IS = re.compile(
    rf"{_LEAD}{_THE}session{_NUM}{_BE}\s+(?:(?P<done>{_DONE})|(?P<skip>{_SKIP})){_END}", _I
)
# "I did the session [7]", "done with session 7"
_I_DID = re.compile(
    rf"{_LEAD}(?:i\s+(?:did|finished|completed|have\s+done)|done\s+with){_BE}\s+{_THE}session{_NUM}{_END}",
    _I,
)
# "I skipped the session [7]", "skip session 3", "I missed session 7"
_I_SKIPPED = re.compile(
    rf"{_LEAD}(?:i\s+(?:skipped|missed)|skip|skipping){_BE}\s+{_THE}session{_NUM}{_END}", _I
)
_PLANS = re.compile(
    rf"{_LEAD}(?:(?:show|list|what\s+are)\s+(?:me\s+)?{_THE}(?:study\s+)?plans?"
    rf"|how\s+is\s+{_THE}(?:study\s+)?plan\s+going)\s*[?.!]*\s*$",
    _I,
)
_REPLAN = re.compile(
    rf"{_LEAD}(?:re-?plan|reschedule|move)\s+{_THE}(?:skipped\s+)?(?:study\s+)?sessions?{_END}", _I
)


def _answer(answer: str, number: str | None) -> NoAIRoute:
    args = {"answer": answer, **({"session": number} if number else {})}
    return NoAIRoute((NoAICall(CHECKIN, args),))


def route(text: str, now: datetime) -> NoAIRoute | None:
    """The plan call these words ask for, or None (not ours)."""
    del now  # a check-in answer needs no clock: the service knows which session waits
    if len(text) > 200:
        return None
    if m := _SESSION_IS.match(text):
        return _answer("done" if m.group("done") else "skipped", m.group(1))
    if m := _I_DID.match(text):
        return _answer("done", m.group(1))
    if m := _I_SKIPPED.match(text):
        return _answer("skipped", m.group(1))
    if _PLANS.match(text):
        return NoAIRoute((NoAICall(LIST, {}),))
    if _REPLAN.match(text):
        return NoAIRoute((NoAICall(RESCHEDULE, {}),))
    return None


__all__ = ["route"]
