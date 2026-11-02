# src/jarvis/web/ports.py
"""The search port (slice 10 B): what JARVIS needs from any web-search vendor. The Tavily adapter
(`jarvis.web.tavily`) is today's implementation; another vendor is one new adapter, no tool
changes. Results are plain data with every field already type-checked; nothing here is trusted
(titles, snippets and page text are other people's words: the tools fence them).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

Topic = Literal["general", "news"]


class WebError(RuntimeError):
    """A search or page read failed; the message is plain English, free of vendor text."""


class CreditsExhausted(WebError):
    """The vendor says the plan's (or pay-as-you-go) credits are used up: the month is latched
    as used up, so nothing more is sent until it resets."""


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str  # as the vendor sent it; the tools normalise (https only) before use
    content: str  # the vendor's query-relevant snippet
    published: str | None = None


@dataclass(frozen=True)
class SearchPage:
    hits: list[SearchHit] = field(default_factory=list)
    credits: int | None = None  # what the vendor says it charged, when it says


@dataclass(frozen=True)
class PageText:
    url: str
    text: str = ""
    ok: bool = False
    reason: str = ""  # plain words when not ok
    credits: int | None = None


@runtime_checkable
class SearchProvider(Protocol):
    name: str

    async def search(
        self, query: str, *, max_results: int, topic: Topic, days: int | None
    ) -> SearchPage: ...

    async def extract(self, url: str) -> PageText: ...

    async def aclose(self) -> None: ...


__all__ = [
    "CreditsExhausted",
    "PageText",
    "SearchHit",
    "SearchPage",
    "SearchProvider",
    "Topic",
    "WebError",
]
