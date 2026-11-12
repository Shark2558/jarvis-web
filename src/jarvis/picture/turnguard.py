# src/jarvis/picture/turnguard.py
"""No name from a face on the main brain's path (R11.1 D21-D; security review H1, M3; Layer 4).

The main brain is shown the owner's attached picture (Part B's `with_pictures`), so a sentence in
the persona is not enough to keep it from turning a face into a name and handing that name to a
tool. This module is the code-level, turn-scoped guard every tool that takes a person's name or a
web query calls, inside the tool call:

- **Outside a Brain turn** (`taint.owner_text()` is None: the People panel's own route, a card he
  approved, a script) nothing changes: the owner pressed it himself.
- **A turn whose latest owner message carried NO picture** is unchanged.
- **A picture turn** (or one JARVIS can't be sure about: fail closed):
  - a person's name is accepted only when every word of it is a whole word of what the owner
    typed in that message (`check_name`);
  - else, when the conversation's last `picture_research` report read it off the picture's own
    text, the call becomes an OFFER (`Offer`: a "Look up" button he presses, fixed words, with
    the line it was read from): nothing is researched;
  - else it is refused in fixed words (`NO_IDENTIFY`);
  - a web query may carry no person-shaped phrase whose words he did not type and the picture
    does not show (`check_query`); else it is refused in fixed words (`WEB_REFUSED`).

"Did the latest owner message carry a picture?" is asked through a port (`PictureTurns`), whose
real adapter (`DocumentTurns`) reads Part B's contract (`documents.pictures.turn_pictures`). Its
answer is "yes", "no" or "unknown"; unknown, a fault, no port and no tool context all count as a
picture turn. `app_guard(state)` is the one call the app makes to build it from its own state.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

from jarvis.documents.pictures import turn_pictures
from jarvis.logging import get_logger
from jarvis.picture.guard import NO_IDENTIFY
from jarvis.picture.words import (
    NOT_NAME,
    WORD,
    capitalised,
    contains,
    name_shaped,
    person_shaped,
    plain,
    word_set,
    words_of,
)
from jarvis.tools.context import current_tool_context
from jarvis.tools.taint import owner_text

if TYPE_CHECKING:  # web.tools imports this module: nothing here may import the web search
    from jarvis.picture.research import Report

log = get_logger(__name__)

Carried = Literal["yes", "no", "unknown"]
OFFER_WORDS = (
    "The picture's text names {name}. Press 'Look up' to check them with your people research."
)
WEB_REFUSED = (
    "I don't identify people from pictures, Sir, so I didn't search the web for that. On a "
    "message with a picture I search only for words you typed or words the picture shows."
)
LOOK = "look"  # Part D's part and its service on `app.state.r111_parts` (picture.part)
RESEARCH = "research"


class PictureTurns(Protocol):
    """The port: did the LATEST owner message of this conversation carry a picture?"""

    async def carried(self, uid: str, session_id: str) -> Carried: ...


LastReport = Callable[[str, str], "Report | None"]


@dataclass(frozen=True)
class Allowed:
    """Go ahead: the call is unchanged."""


@dataclass(frozen=True)
class Offer:
    """A name the picture's own text holds: offered, never looked up by the call itself."""

    name: str
    caption: str  # the line of the picture's text it was read from

    def words(self) -> str:
        return OFFER_WORDS.format(name=self.name)


@dataclass(frozen=True)
class Refused:
    message: str

    def view(self) -> dict[str, Any]:
        """A refusal as a tool's normal result, in fixed words."""
        return {"refused": True, "message": self.message, "spoken": self.message}


ALLOWED = Allowed()


# ---- the pure checks (a picture turn) ----------------------------------------------------------
def check_name(name: str, typed: str, picture_text: Sequence[str]) -> Allowed | Offer | Refused:
    """A person's name on a picture turn: typed by him, an offer from the picture's text, or no."""
    wanted = words_of(name)
    if wanted and set(wanted) <= word_set([typed]):
        return ALLOWED
    if wanted and name_shaped(name):
        line = next((t for t in picture_text if contains(words_of(t), wanted)), "")
        if line:
            return Offer(name, line)
    return Refused(NO_IDENTIFY)


def _named_by_capitals(words: list[str], known: frozenset[str]) -> bool:
    """A capitalised word (ALL CAPS too) he did not type and the picture does not show, unless
    it is the query's lone opening capital ("Price of ...") or a small word."""
    for i, word in enumerate(words):
        if not capitalised(word) or plain(word) in known or plain(word) in NOT_NAME:
            continue
        if i > 0 or (len(words) > 1 and capitalised(words[1])):
            return True
    return False


def check_query(query: str, typed: str, picture_text: Sequence[str]) -> Allowed | Refused:
    """A web query on a picture turn: no person-shaped phrase whose words he did not type or the
    picture does not show. `picture_text`: the picture's text and its vetted things' names."""
    known = word_set([typed, *picture_text])
    folded = words_of(query)
    if person_shaped(query) and not set(folded) <= known:
        return Refused(WEB_REFUSED)  # "who is the woman in red", "actress with short hair"
    if _named_by_capitals(WORD.findall(query), known):
        return Refused(WEB_REFUSED)  # "Lekha Examplekar minister", "LEKHA EXAMPLEKAR"
    if name_shaped(query) and not set(folded) & known:
        return Refused(WEB_REFUSED)  # a bare name, also in lower case
    return ALLOWED


# ---- the turn ------------------------------------------------------------------------------------
class TurnGuard:
    """`turns`: the port (None: not wired, so every turn is a picture turn). `last`: the
    conversation's last picture report (None: no picture research here)."""

    def __init__(self, turns: PictureTurns | None = None, last: LastReport | None = None) -> None:
        self._turns, self._last = turns, last

    async def _picture_turn(self) -> tuple[bool, Report | None]:
        """Is this call on a picture turn (or one JARVIS can't be sure about), and the last
        picture report of this conversation."""
        ctx = current_tool_context()
        if ctx is None or ctx.session_id is None:
            return True, None
        uid, sid = ctx.user_id, ctx.session_id
        carried: Carried = "unknown"
        if self._turns is not None:
            try:
                carried = await self._turns.carried(uid, sid)
            except Exception as exc:  # noqa: BLE001 - a fault counts as a picture turn
                log.warning("picture turn unknown", extra={"reason": type(exc).__name__})
        if carried == "no":
            return False, None
        return True, self._report(uid, sid)

    def _report(self, uid: str, sid: str) -> Report | None:
        try:
            return self._last(uid, sid) if self._last is not None else None
        except Exception as exc:  # noqa: BLE001 - no report: nothing can be offered
            log.warning("picture report unreadable", extra={"reason": type(exc).__name__})
            return None

    async def name(self, name: str) -> Allowed | Offer | Refused:
        """May a tool use this person's name in the current call?"""
        typed = owner_text()
        if typed is None:
            return ALLOWED  # outside a Brain turn: his own press
        first = check_name(name, typed, ())
        if isinstance(first, Allowed):
            return first
        picture, report = await self._picture_turn()
        if not picture:
            return ALLOWED
        return check_name(name, typed, report.text if report is not None else ())

    async def query(self, query: str) -> Allowed | Refused:
        """May `web_search` send this query in the current call?"""
        typed = owner_text()
        if typed is None or isinstance(check_query(query, typed, ()), Allowed):
            return ALLOWED
        picture, report = await self._picture_turn()
        if not picture:
            return ALLOWED
        shown = [*report.text, *(s.name for s in report.subjects)] if report is not None else []
        return check_query(query, typed, shown)

    async def query_stop(self, query: str) -> dict[str, Any] | None:
        """The one call `web_search`'s run makes: its result when the query is refused, else
        None (go ahead)."""
        verdict = await self.query(query)
        return verdict.view() if isinstance(verdict, Refused) else None


FAIL_CLOSED = TurnGuard()  # not wired: every Brain turn counts as a picture turn


# ---- the port over Part B's contract, and the app's one call -------------------------------------
class DocumentTurns:
    """`PictureTurns` over `documents.pictures.turn_pictures` (Part B), the document service read
    late. No store: no picture can have been attached ("no"). A fault, or an answer that is not
    a list, is "unknown"."""

    def __init__(self, docs: Callable[[], Any]) -> None:
        self._docs = docs

    async def carried(self, uid: str, session_id: str) -> Carried:
        docs = self._docs()
        if docs is None:
            return "no"
        try:
            pictures = await turn_pictures(docs, uid, session_id)
        except Exception as exc:  # noqa: BLE001 - a storage fault is not "no picture"
            log.warning("turn pictures unreadable", extra={"reason": type(exc).__name__})
            return "unknown"
        if not isinstance(pictures, list):
            return "unknown"
        return "yes" if pictures else "no"


def app_guard(state: Callable[[str], Any]) -> TurnGuard:
    """The guard for an app: `app_guard(lambda name: getattr(app.state, name, None))`. Reads the
    document service and Part D's last picture report LATE, when a tool is called."""

    def last(uid: str, session_id: str) -> Report | None:
        parts = state("r111_parts") or {}
        part = parts.get(LOOK) if isinstance(parts, dict) else None
        service = part.services.get(RESEARCH) if part is not None else None
        from jarvis.picture.research import Report  # late: see the import note above

        read = getattr(service, "last", None)
        found = read(uid, session_id) if callable(read) else None
        return found if isinstance(found, Report) else None

    return TurnGuard(DocumentTurns(lambda: state("documents")), last)


__all__ = [
    "ALLOWED",
    "FAIL_CLOSED",
    "OFFER_WORDS",
    "WEB_REFUSED",
    "Allowed",
    "Carried",
    "DocumentTurns",
    "Offer",
    "PictureTurns",
    "Refused",
    "TurnGuard",
    "app_guard",
    "check_name",
    "check_query",
]
