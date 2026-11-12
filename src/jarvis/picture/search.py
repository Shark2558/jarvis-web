# src/jarvis/picture/search.py
"""The web search behind picture research (R11.1 D17; Layer 6). A query that the guard allowed
(`jarvis.picture.guard`: a thing, never a person) is searched here under every rule a typed
`web_search` obeys:

- **The owner's "Search the web" row decides.** The read is asked of the gateway's own policy and
  rules through `tools.background.BackgroundReads` (the one governed path for a read made on a
  tool's behalf). "Allow" searches; "Ask first" and "Never" do not: the card he saw, if any, was
  for the picture, not for a search. It leaves one kind-only audit line, never the query.
- **Private details never reach the vendor** (`web.guard.query_problem`), and a query is short.
- **The same caps**: the per-message and hourly search caps and the month's allowance, counted
  where `web_search` counts them (the conversation's ledger, `WebService`, `WebAllowance`). A
  research made outside a conversation (the console's press) counts against the picture's own
  message (`message`), so presses on one message never search more than one message may.
- **Its own deadline** (`SEARCH_TIMEOUT_S`): a vendor that hangs ends in plain words.
- **Results are other people's words.** Only https pages are kept, numbered in the
  conversation's ledger when there is one (so a reply's [n] becomes a source chip exactly as for
  `web_search`). The model is never shown a link; the owner's console is.
- **The last net.** Pages that are a person's own profiles or read as a biography are dropped;
  when most of what came back is about a person, nothing is kept and the answer says so. People
  are researched only by `research_person`, behind its check.
"""

from __future__ import annotations

import asyncio
import re
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from jarvis.logging import get_logger
from jarvis.people.gate import is_personal_social
from jarvis.people.research import SearchFailed, WebSearcher
from jarvis.people.sources import classify_profile
from jarvis.tools.background import BackgroundReads, GatewayView
from jarvis.tools.card import one_line
from jarvis.tools.external import clean_text
from jarvis.web.guard import query_problem
from jarvis.web.ledger import current_conversation
from jarvis.web.ports import SearchHit
from jarvis.web.service import WebService
from jarvis.web.sources import domain_of, normalize_url
from jarvis.web.tools import MAX_SEARCHES_PER_HOUR, MAX_SEARCHES_PER_TURN

log = get_logger(__name__)

JOB = "picture_research"
WEB_TOOL = "web_search"
MAX_RESULTS = 3
ASKED_RESULTS = 5  # asked of the vendor: some are dropped (not https, a person's profile)
QUERY_MAX = 100
SEARCH_TIMEOUT_S = 15.0
MAX_MESSAGES = 64  # the messages whose console searches are counted (the oldest let go)
TITLE_MAX = 160
SNIPPET_MAX = 500
WEB_OFF = "Web search isn't set up here, so I have no sources."
ASK_FIRST = (
    "Web search is set to 'Ask first' in Permissions, so I looked without searching. "
    "Ask me to search for it and I'll put up the card."
)
NEVER = "Web search is set to 'Never' in Permissions, so I looked without searching."
ROWS_UNREADABLE = "I couldn't read your permissions just now, so I didn't search the web."
TURN_LIMIT = "This message has used its web searches, so I didn't search again."
HOUR_LIMIT = "Too many web searches in the last hour, so I didn't search. Try again later."
PRIVATE = "I didn't search for one thing in it: its name holds a private detail ({what})."
ABOUT_A_PERSON = (
    "What the search found was about a person, so I left it out: I research people only in "
    "People, with its check."
)
NOTHING_FOUND = "The search found nothing I could use."
SEARCH_SLOW = "The web search took too long, so I have no sources. Try again in a minute."
Status = Literal["found", "none", "off", "not_allowed", "limit", "refused", "failed", "person"]
_PROFILE_PLATFORMS = frozenset({"linkedin", "x", "instagram", "facebook", "youtube"})
_BIOGRAPHY = re.compile(
    r"\(\s*born\b|\bborn\s+(?:on\s+)?\d|\bdate\s+of\s+birth\b"
    r"|\bis\s+an?\s+[\w ,\-]{0,40}?\b(?:actor|actress|politician|singer|musician|cricketer|"
    r"footballer|athlete|businessman|businesswoman|entrepreneur|author|writer|journalist|model|"
    r"director|producer|lawyer|doctor|professor|activist|minister|comedian|dancer)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Source:
    n: int  # its number in the conversation (or in this answer, outside one)
    title: str
    domain: str
    url: str  # https, canonical: for the owner's console, never shown to a model
    snippet: str


@dataclass(frozen=True)
class Found:
    status: Status
    sources: tuple[Source, ...] = ()
    note: str = ""  # plain words when nothing is shown


class Finder(Protocol):
    async def find(self, uid: str, query: str, *, message: str | None = None) -> Found: ...


def about_a_person(hit: SearchHit) -> bool:
    """Is this page a person's own profile, a personal social page, or a biography?"""
    link = classify_profile(hit.url)
    if link is not None and link.platform in _PROFILE_PLATFORMS:
        return True
    if is_personal_social(hit.url):
        return True
    return _BIOGRAPHY.search(f"{hit.title} {hit.content}") is not None


class WebFinder:
    """`web` and `gateway` are read LATE (the app builds them around this part). None for the
    web service means "not set up"; no gateway means no governed path, so no search."""

    def __init__(
        self,
        web: Callable[[], WebService | None],
        gateway: Callable[[], GatewayView | None],
    ) -> None:
        self._web, self._gateway = web, gateway
        self._reads: tuple[int, BackgroundReads] | None = None
        self._pressed: OrderedDict[tuple[str, str], int] = OrderedDict()

    def _governed(self, gateway: GatewayView) -> BackgroundReads:
        """One `BackgroundReads` per gateway object (it remembers what it already audited)."""
        if self._reads is None or self._reads[0] != id(gateway):
            self._reads = (id(gateway), BackgroundReads.of(gateway))
        return self._reads[1]

    async def _allowed(self, uid: str) -> tuple[BackgroundReads | None, str]:
        gateway = self._gateway()
        if gateway is None:
            return None, ROWS_UNREADABLE
        reads = self._governed(gateway)
        verdict = await reads.allowed(uid, WEB_TOOL, job=JOB)
        if verdict.ok:
            return reads, ""
        words = {"ask_first": ASK_FIRST, "denied": NEVER}.get(verdict.reason, ROWS_UNREADABLE)
        return None, WEB_OFF if verdict.why == "unknown tool" else words

    def _message_used(self, uid: str, message: str | None) -> int:
        return self._pressed.get((uid, message), 0) if message is not None else 0

    def _bump_message(self, uid: str, message: str | None) -> None:
        if message is None:
            return
        key = (uid, message)
        self._pressed[key] = self._pressed.pop(key, 0) + 1
        while len(self._pressed) > MAX_MESSAGES:
            self._pressed.popitem(last=False)

    def _capped(self, web: WebService, uid: str, message: str | None) -> str:
        """Count this search against the message's and the hour's caps; the words when one is
        hit ("" when it may go ahead). In a conversation its ledger counts; outside one (the
        console's press) the picture's own message does."""
        conv = current_conversation()
        used = conv.used("search") if conv is not None else self._message_used(uid, message)
        if used >= MAX_SEARCHES_PER_TURN:
            return TURN_LIMIT
        if web.searches_last_hour(uid) >= MAX_SEARCHES_PER_HOUR:
            return HOUR_LIMIT
        if conv is not None:
            conv.bump("search")
        else:
            self._bump_message(uid, message)
        web.count_search(uid)
        return ""

    async def find(self, uid: str, query: str, *, message: str | None = None) -> Found:
        web = self._web()
        if web is None:
            return Found("off", note=WEB_OFF)
        query = one_line(query, QUERY_MAX)
        if (what := query_problem(query)) is not None:
            return Found("refused", note=PRIVATE.format(what=what))
        reads, why = await self._allowed(uid)
        if reads is None:
            return Found("off" if why == WEB_OFF else "not_allowed", note=why)
        if capped := self._capped(web, uid, message):
            return Found("limit", note=capped)
        try:
            async with asyncio.timeout(SEARCH_TIMEOUT_S), reads.reading(WEB_TOOL, job=JOB):
                hits = await WebSearcher(web).search(query, max_results=ASKED_RESULTS)
        except SearchFailed as exc:  # our own plain words (the month is used up, not available)
            return Found("failed", note=str(exc))
        except TimeoutError:
            log.warning("picture search timed out")
            return Found("failed", note=SEARCH_SLOW)
        return _kept(hits)


def _kept(hits: list[SearchHit]) -> Found:
    """The https pages that are not about a person, numbered; or why none is shown."""
    usable = [h for h in hits if normalize_url(h.url) is not None]
    people = [h for h in usable if about_a_person(h)]
    if usable and 2 * len(people) >= len(usable):
        return Found("person", note=ABOUT_A_PERSON)
    conv = current_conversation()
    sources: list[Source] = []
    for h in usable:
        url = normalize_url(h.url)
        if url is None or h in people or any(s.url == url for s in sources):
            continue
        title = one_line(clean_text(h.title), TITLE_MAX) or "(no title)"
        n = conv.add(title, url) if conv is not None else len(sources) + 1
        snippet = one_line(clean_text(h.content), SNIPPET_MAX)
        sources.append(Source(n, title, domain_of(url), url, snippet))
        if len(sources) >= MAX_RESULTS:
            break
    if not sources:
        return Found("none", note=NOTHING_FOUND)
    return Found("found", tuple(sources))


__all__ = [
    "ABOUT_A_PERSON",
    "ASK_FIRST",
    "JOB",
    "MAX_RESULTS",
    "NEVER",
    "SEARCH_SLOW",
    "SEARCH_TIMEOUT_S",
    "WEB_OFF",
    "Finder",
    "Found",
    "Source",
    "WebFinder",
    "about_a_person",
]
