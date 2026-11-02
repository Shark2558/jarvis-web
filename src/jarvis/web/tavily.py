# src/jarvis/web/tavily.py
"""Tavily adapter for the `SearchProvider` port (slice 10 B; Layer 6). Direct REST over httpx — no
vendor SDK. Request/response shapes, auth and error codes verified against docs.tavily.com on
2026-11-01 (recorded in docs/plans/phase2-slice10-tools-wave.md, section B).

    POST https://api.tavily.com/search    basic depth (1 credit), ≤ 5 results, no answer / raw
                                          content / images / favicons, include_usage
    POST https://api.tavily.com/extract   one URL, basic depth, plain text (1 credit per 5
                                          successful URLs; a failed one is not charged)
    GET  https://api.tavily.com/usage     slice 11 D7 b: {key: {usage, limit (null: none), …},
                                          account: {current_plan, plan_usage, plan_limit,
                                          paygo_usage, paygo_limit, …}} for the current billing
                                          cycle (docs.tavily.com/documentation/api-reference/
                                          endpoint/usage, checked 2026-11-02; not among the
                                          credit-charging endpoints on the API-credits page)

Auth is the bearer header only (the key never goes in a body, a log line or an error). Every call
has an overall deadline; redirects are not followed; the response is read in a stream and refused
past `MAX_RESPONSE_BYTES`; every field is type-checked and anything malformed is dropped (or the
whole answer is "unreadable"). Errors carry plain English per status — never Tavily's own text.
Fetching a page is Tavily's job, never this server's: no request to the page's host leaves here.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from pydantic import SecretStr

from jarvis.logging import get_logger
from jarvis.tools.card import one_line
from jarvis.web.ports import (
    CreditsExhausted,
    PageText,
    SearchHit,
    SearchPage,
    Topic,
    VendorUsage,
    WebError,
)

log = get_logger(__name__)

SEARCH_URL = "https://api.tavily.com/search"
EXTRACT_URL = "https://api.tavily.com/extract"
USAGE_URL = "https://api.tavily.com/usage"
DEADLINE_S = 25.0  # the whole call, connect to last byte
HTTP_TIMEOUT = httpx.Timeout(20.0, connect=5.0)
EXTRACT_TIMEOUT_S = 15  # Tavily's own time budget to fetch the page (1–60)
MAX_RESPONSE_BYTES = 2_000_000
MAX_HITS = 20
FIELD_LIMIT = 20_000  # characters kept per vendor field before the tools apply their own caps
MAX_PAGE_CHARS = 200_000
URL_LIMIT = 4096
DATE_LIMIT = 40
NOT_READ = "the page could not be read (it may block readers, need a sign-in, or not be text)"

_FRIENDLY: dict[int, str] = {
    400: "Tavily rejected the request as invalid.",
    401: "Tavily refused the API key (check the jarvis-tavily-key secret).",
    403: "Tavily refused the API key (check the jarvis-tavily-key secret).",
    422: "Tavily rejected the request as invalid.",
    429: "Tavily says there have been too many searches just now; try again in a minute.",
    432: "Tavily says this month's free credits are used up.",
    433: "Tavily's pay-as-you-go limit was reached, so nothing was searched.",
    434: "Tavily is busy right now; try again shortly.",
}


USED_UP = frozenset({432, 433})  # plan / key limit, pay-as-you-go limit: latch the month


def _friendly(status: int) -> str:
    if status in _FRIENDLY:
        return _FRIENDLY[status]
    if status >= 500:
        return "Tavily is temporarily unavailable; try again shortly."
    return f"Tavily returned an unexpected status ({status})."


def _time_range(days: int | None) -> str | None:
    """Our `days` argument → Tavily's `time_range` (its old `days` field is gone)."""
    if days is None:
        return None
    if days <= 1:
        return "day"
    if days <= 7:
        return "week"
    return "month" if days <= 31 else "year"


def _text(v: object, limit: int = FIELD_LIMIT) -> str:
    return v[:limit] if isinstance(v, str) else ""


def _date(v: object) -> str | None:
    return (one_line(v, DATE_LIMIT) or None) if isinstance(v, str) else None


def _credits(data: dict[str, Any]) -> int | None:
    usage = data.get("usage")
    c = usage.get("credits") if isinstance(usage, dict) else None
    return c if isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 1000 else None


def _count(v: object) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def _part(data: dict[str, Any], name: str) -> dict[str, Any]:
    part = data.get(name)
    return part if isinstance(part, dict) else {}


def _vendor_usage(data: dict[str, Any]) -> VendorUsage:
    """GET /usage → (used, limit, exhausted), from the key's and the plan's counts: the larger
    count, the smaller limit, and "exhausted" when either count has reached its limit."""
    key, account = _part(data, "key"), _part(data, "account")
    pairs = [
        (_count(key.get("usage")), _count(key.get("limit"))),
        (_count(account.get("plan_usage")), _count(account.get("plan_limit"))),
    ]
    used = [u for u, _ in pairs if u is not None]
    if not used:
        raise WebError("Tavily returned an unreadable usage report.")
    limits = [lim for _, lim in pairs if lim is not None]
    exhausted = any(u is not None and lim is not None and u >= lim for u, lim in pairs)
    return VendorUsage(max(used), min(limits) if limits else None, exhausted)


class TavilyProvider:
    name = "tavily"

    def __init__(
        self,
        api_key: SecretStr,
        *,
        http: httpx.AsyncClient | None = None,
        deadline_s: float = DEADLINE_S,
    ) -> None:
        self._key = api_key
        self._own = http is None
        self.http = http or httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=False)
        self._deadline = deadline_s

    async def aclose(self) -> None:
        if self._own:
            await self.http.aclose()

    # ---- the one door ----------------------------------------------------------------------

    async def _call(
        self, method: str, url: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        headers = {  # stripped: a Secret Manager value often ends with a newline
            "Authorization": f"Bearer {self._key.get_secret_value().strip()}",
            "Accept": "application/json",
        }
        try:
            async with asyncio.timeout(self._deadline):
                async with self.http.stream(
                    method, url, json=body, headers=headers, timeout=HTTP_TIMEOUT
                ) as r:
                    if r.status_code != 200:
                        path = httpx.URL(url).path
                        log.warning("tavily error", extra={"status": r.status_code, "path": path})
                        if r.status_code in USED_UP:
                            raise CreditsExhausted(_friendly(r.status_code))
                        raise WebError(_friendly(r.status_code))
                    raw = await self._read_capped(r)
        except TimeoutError as exc:
            raise WebError("Tavily took too long to answer; try again shortly.") from exc
        except httpx.HTTPError as exc:
            log.warning("tavily unreachable", extra={"reason": type(exc).__name__})
            raise WebError("Could not reach Tavily; try again shortly.") from exc
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise WebError("Tavily returned an unreadable response.") from exc
        if not isinstance(data, dict):
            raise WebError("Tavily returned an unreadable response.")
        return data

    @staticmethod
    async def _read_capped(r: httpx.Response) -> bytes:
        chunks: list[bytes] = []
        size = 0
        async for chunk in r.aiter_bytes():
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise WebError("Tavily's answer was too large to use.")
            chunks.append(chunk)
        return b"".join(chunks)

    # ---- search ----------------------------------------------------------------------------

    async def search(
        self, query: str, *, max_results: int, topic: Topic, days: int | None
    ) -> SearchPage:
        body: dict[str, Any] = {
            "query": query,
            "search_depth": "basic",
            "topic": topic,
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "include_favicon": False,
            "include_usage": True,
        }
        if (span := _time_range(days)) is not None:
            body["time_range"] = span
        data = await self._call("POST", SEARCH_URL, body)
        results = data.get("results")
        if not isinstance(results, list):
            raise WebError("Tavily returned an unreadable response.")
        hits: list[SearchHit] = []
        for item in results[:MAX_HITS]:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if not isinstance(url, str) or not url.strip() or len(url) > URL_LIMIT:
                continue
            hits.append(
                SearchHit(
                    title=_text(item.get("title")),
                    url=url.strip(),
                    content=_text(item.get("content")),
                    published=_date(item.get("published_date")),
                )
            )
        return SearchPage(hits=hits, credits=_credits(data))

    # ---- extract ---------------------------------------------------------------------------

    async def extract(self, url: str) -> PageText:
        body = {
            "urls": [url],
            "extract_depth": "basic",
            "format": "text",
            "include_images": False,
            "include_favicon": False,
            "timeout": EXTRACT_TIMEOUT_S,
            "include_usage": True,
        }
        data = await self._call("POST", EXTRACT_URL, body)
        credits = _credits(data)
        results = data.get("results")
        for item in results if isinstance(results, list) else []:
            text = item.get("raw_content") if isinstance(item, dict) else None
            if isinstance(text, str) and text.strip():
                return PageText(url=url, text=text[:MAX_PAGE_CHARS], ok=True, credits=credits)
        return PageText(url=url, ok=False, reason=NOT_READ, credits=credits)

    # ---- usage (slice 11 D7 b) -------------------------------------------------------------

    async def usage(self) -> VendorUsage:
        """Tavily's own count for its current billing cycle; no body, no credit."""
        return _vendor_usage(await self._call("GET", USAGE_URL))


__all__ = ["EXTRACT_URL", "MAX_RESPONSE_BYTES", "SEARCH_URL", "USAGE_URL", "TavilyProvider"]
