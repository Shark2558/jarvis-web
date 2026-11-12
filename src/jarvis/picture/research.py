# src/jarvis/picture/research.py
"""Research a picture the owner attached (R11.1 D17, D21-D; Layer 5 Research & Intel).

    the turn's pictures (Part B's `turn_pictures`) -> ONE look (`eyes`) -> strict JSON ->
    the guard (`guard.judge`: what may be said, what may be searched) -> web search for the
    THINGS (`search.Finder`) -> a `Report`

What the owner declined to get stays declined: nobody is identified from a picture. A picture
with a person gets the fixed reply (what is visible, then `guard.NO_IDENTIFY`) and no search
carries the person. A name can come only from the picture's own words, as an offer to look it up
with `research_person`, behind its unchanged check.

Every way it can't work says why in plain words and searches nothing: switched off, no picture
with the last message, the AI off, no brain that may see a picture, the monthly limit, the AI
unreachable, an answer that is not the schema, too many looks in a minute.

Nothing is kept: the picture is handed to the eyes and dropped; the look's raw answer never
leaves this call; the last FINISHED `Report` of a conversation (words and links, never a picture)
stays in memory for `KEEP_S` (at most `MAX_KEPT`, the oldest let go first) so the console's route
can show the links a model is never shown, and so `jarvis.picture.turnguard` can tell a name the
picture's text holds from one taken from a face. A look that failed never replaces it.

The searches of a research made outside a conversation (the console's press) are counted against
the picture's own message (`message_key`: the same pictures are the same message), so presses on
one message keep the message's search cap as `web_search` does.
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from jarvis.llm.base import ImageBlock
from jarvis.logging import get_logger
from jarvis.picture.eyes import LOOK_ASK, LOOK_SYSTEM, CantLook, Eyes
from jarvis.picture.guard import NO_IDENTIFY, Subject, Verdict, judge, parse_seen
from jarvis.picture.search import Finder, Found, Source

log = get_logger(__name__)

LOOK_TOKENS = 700
RATE_BURST = 4
RATE_WINDOW_S = 60.0
KEEP_S = 600.0
MAX_KEPT = 64  # reports kept in memory (one per conversation), for `KEEP_S` at most
OFF = "Picture research is switched off on this JARVIS, Sir."
NO_PICTURE = (
    "There is no picture with your last message in this conversation, Sir. Attach one, send "
    "it, and ask again."
)
ONLY_N = "There {are} only {n} picture{s} with your last message, Sir."
# R11.1 I1: Part B's `turn_pictures` could not read them (a storage fault, a picture that would
# not load): said as such, never as "there is no picture"
PICTURES_UNREADABLE = (
    "I couldn't read the picture with your last message just now, Sir. Please try again in a "
    "moment."
)
UNREADABLE = "I couldn't make sense of that picture just now, Sir. Please try again."
TOO_MANY = "That is a lot of pictures in a minute, Sir. Give it a moment."
NOT_A_THING = (
    "I didn't search the web: nothing in it is named clearly enough as a thing for me to look up."
)
READS = "It reads: {text}."
FOUND = "I found {n} source{s} for {name}."
OFFER = (
    "The picture's text names {name}. Caption read: '{caption}'. Shall I look {name} up from "
    "public sources, Sir?"
)
Status = Literal[
    "done", "off", "no_picture", "busy", "no_ai", "blind", "limit", "unreachable", "unreadable"
]
PictureSource = Callable[[str, str], Awaitable[list[ImageBlock]]]


@dataclass(frozen=True)
class Finding:
    """One thing that was searched for, and what came back (or why nothing is shown)."""

    subject: Subject
    found: Found

    @property
    def sources(self) -> tuple[Source, ...]:
        return self.found.sources


@dataclass(frozen=True)
class Report:
    """What one research answered. `message` is always the whole reply in fixed-template words;
    the other fields are for the tool's fenced view and the console."""

    status: Status
    message: str
    person: bool = False
    scene: str = ""
    text: tuple[str, ...] = ()
    subjects: tuple[Subject, ...] = ()
    findings: tuple[Finding, ...] = ()
    named: str = ""
    pictures: int = 0
    cost_usd: float = 0.0
    caption: str = ""  # the line of the picture's text `named` was read from


def _plural(n: int) -> str:
    return "" if n == 1 else "s"


def _search_words(findings: tuple[Finding, ...]) -> list[str]:
    """One sentence per searched thing: how many sources, or why there are none."""
    out: list[str] = []
    for f in findings:
        n = len(f.found.sources)
        words = FOUND.format(n=n, s=_plural(n), name=f.subject.name) if n else f.found.note
        if words and words not in out:
            out.append(words)
    return out


def compose(v: Verdict, findings: tuple[Finding, ...]) -> str:
    """The whole reply, from fixed templates. With a person in the picture: what is visible, the
    one fixed sentence, then only what was found about THINGS and (D21-D) the offer."""
    parts = [v.scene] if v.scene else []
    if v.person:
        parts.append(NO_IDENTIFY)
    elif v.text:
        parts.append(READS.format(text="; ".join(v.text)))
    parts += _search_words(findings)
    if not v.person and not findings:
        parts.append(NOT_A_THING)
    if v.named:
        parts.append(OFFER.format(name=v.named, caption=v.caption))
    return " ".join(parts)


def message_key(session_id: str, pictures: list[ImageBlock]) -> str:
    """Which owner message these pictures came with: the same pictures, the same message."""
    seen = hashlib.sha256()
    for p in pictures:
        seen.update(hashlib.sha256(p.data).digest())
    return f"{session_id}:{seen.hexdigest()[:24]}"


class PictureResearch:
    """`guard=False` exists only so the eval can show its negative control (with it off a name
    gets through); it is never read from settings. `clock` is monotonic seconds."""

    def __init__(
        self,
        eyes: Eyes,
        pictures: PictureSource,
        finder: Finder,
        *,
        enabled: bool = True,
        guard: bool = True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.eyes, self.enabled, self.clock = eyes, enabled, clock
        self._pictures, self._finder, self._guard = pictures, finder, guard
        self._calls: dict[str, deque[float]] = {}
        self._last: OrderedDict[tuple[str, str], tuple[float, Report]] = OrderedDict()

    # ---- the last report of a conversation (for the console's route) ----
    def last(self, uid: str, session_id: str) -> Report | None:
        key = (uid, session_id)
        kept = self._last.get(key)
        if kept is None or not 0 <= self.clock() - kept[0] < KEEP_S:
            self._last.pop(key, None)
            return None
        return kept[1]

    def _keep(self, uid: str, session_id: str, report: Report) -> Report:
        """Keep a finished report as the conversation's last; a failed look keeps the one before.
        At the cap the oldest goes."""
        if report.status != "done":
            return report
        key = (uid, session_id)
        self._last.pop(key, None)
        while len(self._last) >= MAX_KEPT:
            self._last.popitem(last=False)
        self._last[key] = (self.clock(), report)
        return report

    def _too_many(self, uid: str) -> bool:
        now = self.clock()
        window = self._calls.setdefault(uid, deque())
        while window and now - window[0] >= RATE_WINDOW_S:
            window.popleft()
        if len(window) >= RATE_BURST:
            return True
        window.append(now)
        return False

    # ---- the flow ----
    async def research(self, uid: str, session_id: str | None, index: int = 1) -> Report:
        """Research picture number `index` (1 = the newest) of the owner's last message in this
        conversation. Never raises for something the owner can act on: it says so."""
        if not self.enabled:
            return Report("off", OFF)
        found = await self._pictures(uid, session_id) if session_id else []
        if session_id and not found and getattr(found, "unreadable", False):
            return Report("unreadable", PICTURES_UNREADABLE)
        if not session_id or not found:
            return Report("no_picture", NO_PICTURE)
        if index > len(found):
            n = len(found)
            words = ONLY_N.format(are="is" if n == 1 else "are", n=n, s=_plural(n))
            return Report("no_picture", words, pictures=n)
        if self._too_many(uid):
            return Report("busy", TOO_MANY)
        message = message_key(session_id, found)
        report = await self._look_and_search(uid, found[index - 1], len(found), message)
        return self._keep(uid, session_id, report)

    async def _look_and_search(
        self, uid: str, picture: ImageBlock, count: int, message: str
    ) -> Report:
        try:
            glance = await self.eyes.look(
                uid, LOOK_SYSTEM, LOOK_ASK, picture, max_tokens=LOOK_TOKENS
            )
        except CantLook as exc:
            return Report(exc.why, str(exc), pictures=count)
        seen = parse_seen(glance.text)
        if seen is None:  # fail closed: nothing is said or searched from it
            log.warning("picture look unreadable", extra={"chars": len(glance.text)})
            return Report("unreadable", UNREADABLE, pictures=count, cost_usd=glance.cost_usd)
        verdict = judge(seen, enabled=self._guard)
        findings = tuple(
            [
                Finding(s, await self._finder.find(uid, s.name, message=message))
                for s in verdict.queries
            ]
        )
        log.info(
            "picture researched",
            extra={
                "person": verdict.person,
                "searched": len(findings),
                "withheld": verdict.withheld,
                "offer": bool(verdict.named),
            },
        )
        return Report(
            status="done",
            message=compose(verdict, findings),
            person=verdict.person,
            scene=verdict.scene,
            text=verdict.text,
            subjects=verdict.subjects,
            findings=findings,
            named=verdict.named,
            pictures=count,
            cost_usd=glance.cost_usd,
            caption=verdict.caption,
        )


__all__ = [
    "KEEP_S",
    "NOT_A_THING",
    "NO_PICTURE",
    "PICTURES_UNREADABLE",
    "OFF",
    "TOO_MANY",
    "UNREADABLE",
    "Finding",
    "PictureResearch",
    "PictureSource",
    "Report",
    "Source",
    "compose",
    "message_key",
]
