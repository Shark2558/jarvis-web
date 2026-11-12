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
  - an outward query (`web_search`, `youtube_search`, `maps_search`, `maps_route`,
    `research_person`'s context) is checked by `check_query` (`jarvis.picture.queries`), in
    STRICT mode unless the picture is KNOWN to show no person: only words he typed, words the
    picture shows, and free words (small, search and thing words) go out. LIGHT mode (known: no
    person) keeps D's name shapes. Else it is refused in fixed words (`WEB_REFUSED`).

"Did the latest owner message carry a picture?" is asked through a port (`PictureTurns`), whose
real adapter (`DocumentTurns`) reads Part B's contract (`documents.pictures.turn_pictures`). Its
answer is "yes", "no" or "unknown"; unknown, a fault, no port and no tool context all count as a
picture turn. "Known to show no person" is the only `has_person` signal the guard has on the main
brain's turn: the conversation's last picture research, when it looked at the ONLY picture of
THIS message (`MessageKeys`: the same key) and saw nobody. No research, an older picture, two
pictures, a fault: strict (R11.1 I1 reviews, security H1 and M3, code M3). `app_guard(state)` is
the one call the app makes to build it from its own state.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

from jarvis.documents.pictures import message_key, pictures_unreadable, turn_pictures
from jarvis.logging import get_logger
from jarvis.picture.guard import NO_IDENTIFY
from jarvis.picture.queries import light_refuses, untold
from jarvis.picture.words import contains, name_shaped, word_set, words_of
from jarvis.tools.base import SUMMARY_FALLBACK_LIMIT, Preview, PreviewFn
from jarvis.tools.card import one_line
from jarvis.tools.context import current_tool_context
from jarvis.tools.taint import owner_text

if TYPE_CHECKING:  # web.tools imports this module: nothing here may import the web search
    from jarvis.picture.research import Report

log = get_logger(__name__)

Carried = Literal["yes", "no", "unknown"]
Mode = Literal["light", "strict"]
LIGHT: Mode = "light"  # the picture is known to show no person
STRICT: Mode = "strict"  # it may show one: only his words, the picture's and free words
OFFER_WORDS = (
    "The picture's text names {name}. Press 'Look up' to check them with your people research."
)
# fixed words, one sentence that says what he can do; they reach the model whole through the
# gateway's 160-character error detail too
WEB_REFUSED = (
    "I don't identify people from pictures, Sir: with a picture I search only your words and the "
    "picture's, so type the name yourself or ask without the picture."
)
WEB_CARD = "Search the web for: {query}"  # web_search's own card words (its summary_template)
LOOK = "look"  # Part D's part and its service on `app.state.r111_parts` (picture.part)
RESEARCH = "research"


class PictureTurns(Protocol):
    """The port: did the LATEST owner message of this conversation carry a picture?"""

    async def carried(self, uid: str, session_id: str) -> Carried: ...


class MessageKeys(Protocol):
    """The port: which owner message the latest pictures came with (`message_key`), or None
    when that can't be told. Binds a picture research report to THIS message."""

    async def message(self, uid: str, session_id: str) -> str | None: ...


LastReport = Callable[[str, str], "Report | None"]
OutwardTexts = Callable[[dict[str, Any]], Sequence[str]]  # the words a tool call sends out


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


class PictureQueryRefused(ValueError):
    """A web query refused on a picture turn: nothing is proposed or searched (the gateway
    reports the fixed words)."""


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


def check_query(
    query: str, typed: str, picture_text: Sequence[str], mode: Mode = LIGHT
) -> Allowed | Refused:
    """An outward query on a picture turn. LIGHT: no person-shaped phrase or name whose words he
    did not type or the picture does not show. STRICT: that, and no word at all beyond his, the
    picture's and the free words. `picture_text`: the picture's text and its vetted things'
    names."""
    if light_refuses(query, word_set([typed, *picture_text])):
        return Refused(WEB_REFUSED)
    if mode == STRICT and untold(query, [typed, *picture_text]):
        return Refused(WEB_REFUSED)  # "narendra modi car", "लेखा", "Lekha weather", a link
    return ALLOWED


# ---- the turn ------------------------------------------------------------------------------------
class TurnGuard:
    """`turns`: the port (None: not wired, so every turn is a picture turn). `last`: the
    conversation's last picture report (None: no picture research here)."""

    def __init__(
        self,
        turns: PictureTurns | None = None,
        last: LastReport | None = None,
        keys: MessageKeys | None = None,
    ) -> None:
        self._turns, self._last, self._keys = turns, last, keys

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

    async def _no_person(self, report: Report | None) -> bool:
        """Is THIS message's picture known to show nobody? Only when the conversation's last
        picture research looked at the only picture this message carried (the same message key)
        and saw no person. Anything else, a fault included, is "maybe": strict."""
        if report is None or report.person or report.pictures != 1 or not report.key:
            return False
        ctx = current_tool_context()
        if self._keys is None or ctx is None or ctx.session_id is None:
            return False
        try:
            return await self._keys.message(ctx.user_id, ctx.session_id) == report.key
        except Exception as exc:  # noqa: BLE001 - can't tell: it may show a person
            log.warning("picture message unknown", extra={"reason": type(exc).__name__})
            return False

    async def query(self, query: str) -> Allowed | Refused:
        """May an outward search (web, YouTube, Maps, people research's context) send this
        query in the current call?"""
        typed = owner_text()
        if typed is None or isinstance(check_query(query, typed, (), STRICT), Allowed):
            return ALLOWED
        picture, report = await self._picture_turn()
        if not picture:
            return ALLOWED
        shown = [*report.text, *(s.name for s in report.subjects)] if report is not None else []
        mode = LIGHT if await self._no_person(report) else STRICT
        return check_query(query, typed, shown, mode)

    async def query_stop(self, query: str) -> dict[str, Any] | None:
        """The one call an outward search's run makes (`web_search`, `youtube_search`,
        `maps_search`, `maps_route`): its result when the query is refused, else None."""
        verdict = await self.query(query)
        return verdict.view() if isinstance(verdict, Refused) else None

    async def query_preview(self, a: dict[str, Any]) -> Preview:
        """`web_search`'s look-up (`Tool.preview`): a query refused on a picture turn is never
        proposed, so an "Ask first" card never shows a name taken from a face."""
        query = str(a.get("query", "")).strip()
        verdict = await self.query(query)
        if isinstance(verdict, Refused):
            raise PictureQueryRefused(verdict.message)
        return Preview(summary=one_line(WEB_CARD.format(query=query), SUMMARY_FALLBACK_LIMIT))

    async def texts_stop(self, texts: Sequence[str]) -> dict[str, Any] | None:
        """`query_stop` for a tool with more than one outward text (Maps: the query and the
        area; a route's two ends): the first refusal's result, else None."""
        for text in texts:
            if text and (stop := await self.query_stop(text)) is not None:
                return stop
        return None

    def preview_for(self, texts: OutwardTexts, card: Callable[[dict[str, Any]], str]) -> PreviewFn:
        """A look-up (`Tool.preview`) for an outward search other than the web's (YouTube,
        Maps): refused texts are never proposed, else the tool's own card words."""

        async def preview(a: dict[str, Any]) -> Preview:
            for text in texts(a):
                verdict = await self.query(text)
                if isinstance(verdict, Refused):
                    raise PictureQueryRefused(verdict.message)
            return Preview(summary=card(a))

        return preview


FAIL_CLOSED = TurnGuard()  # not wired: every Brain turn counts as a picture turn


# ---- the port over Part B's contract, and the app's one call -------------------------------------
class DocumentTurns:
    """`PictureTurns` over `documents.pictures.turn_pictures` (Part B), the document service and
    the conversations (`sessions`, the app's store) read late. No document service: no picture
    can have been attached ("no"). A fault, an answer that is not a list, or one Part B marks
    `unreadable` (a storage fault, a picture that would not load, no conversation store) is
    "unknown": a picture turn (R11.1 I1, GATE C: fail closed)."""

    def __init__(self, docs: Callable[[], Any], sessions: Callable[[], Any] = lambda: None) -> None:
        self._docs, self._sessions = docs, sessions

    async def carried(self, uid: str, session_id: str) -> Carried:
        docs = self._docs()
        if docs is None:
            return "no"
        try:
            pictures = await turn_pictures(docs, uid, session_id, sessions=self._sessions())
        except Exception as exc:  # noqa: BLE001 - a storage fault is not "no picture"
            log.warning("turn pictures unreadable", extra={"reason": type(exc).__name__})
            return "unknown"
        if not isinstance(pictures, list) or pictures_unreadable(pictures):
            return "unknown"
        return "yes" if pictures else "no"

    async def message(self, uid: str, session_id: str) -> str | None:
        """`MessageKeys`: the key of the latest owner message's pictures, as picture research
        computes it; None when there are none or they can't be read."""
        docs = self._docs()
        if docs is None:
            return None
        try:
            pictures = await turn_pictures(docs, uid, session_id, sessions=self._sessions())
        except Exception as exc:  # noqa: BLE001 - can't tell which message
            log.warning("turn pictures unreadable", extra={"reason": type(exc).__name__})
            return None
        if not isinstance(pictures, list) or not pictures or pictures_unreadable(pictures):
            return None
        return message_key(session_id, pictures)


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

    turns = DocumentTurns(lambda: state("documents"), lambda: state("store"))
    return TurnGuard(turns, last, keys=turns)


__all__ = [
    "ALLOWED",
    "FAIL_CLOSED",
    "LIGHT",
    "OFFER_WORDS",
    "STRICT",
    "WEB_CARD",
    "WEB_REFUSED",
    "Allowed",
    "Carried",
    "DocumentTurns",
    "MessageKeys",
    "Mode",
    "Offer",
    "PictureQueryRefused",
    "PictureTurns",
    "Refused",
    "TurnGuard",
    "app_guard",
    "check_name",
    "check_query",
]
