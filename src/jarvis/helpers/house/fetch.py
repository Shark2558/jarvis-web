# src/jarvis/helpers/house/fetch.py
"""Part B's one outbound path (docs/plans/r11-free-helpers.md D20, `helpers.sources`).

`HttpFetcher.get(url, params=, headers=, cap=, timeout_s=)` is a plain GET with `httpx`:
- only to the two fixed hosts (`ALLOWED_HOSTS`: Open-Meteo and NDMA SACHET), https only, no
  redirects followed, so a link inside a feed can never send JARVIS anywhere else (the CAP URL is
  always built from `sources.SACHET_CAP_URL` and a digits-only identifier);
- inside `min(timeout_s, OUTSIDE_TIMEOUT_S)` seconds in all (8 s at most);
- the body read in chunks and refused past `cap` bytes (a declared `Content-Length` too);
- 304 (an `If-None-Match` hit) answers an empty body; any other non-200 is a `FetchError` that
  carries the status (that one resource refused, not the host down);
- a request JARVIS can't build (a header value that isn't ASCII, say) is `BadRequest`: a local
  error, never "unreachable" (security review M2).
Errors carry plain words; the log gets the class name and the status only, never a URL query.
`OutsideClock` splits Part B's share of each clock run into SACHET's slot and weather's slot.
Tests use a fake with the same `get` (tests/r11_fakes_b.py).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

import httpx

from jarvis.helpers.sources import (
    OPEN_METEO_FORECAST_URL,
    OUTSIDE_TIMEOUT_S,
    SACHET_CAP_URL,
    SACHET_RSS_URL,
)
from jarvis.logging import get_logger

log = get_logger(__name__)

ALLOWED_HOSTS = frozenset(
    httpx.URL(u).host
    for u in (OPEN_METEO_FORECAST_URL, SACHET_CAP_URL, SACHET_RSS_URL.format(feed="india"))
)
USER_AGENT = "JARVIS-helpers/11 (personal home automation)"
MIN_TIMEOUT_S = 0.5
# Part B's outside time in one run of the shared helpers clock (D3: 20 s for all four parts'
# jobs, 19 s inside the composite). SACHET and weather each get their own slot and take their
# turns one after the other, so neither can starve the other (code review H1).
SHARE_S = 12.0
SACHET_SLOT_S = 7.0
WEATHER_SLOT_S = 5.0
MIN_LEFT_S = 1.0  # a fetch is started only with at least this much of its slot left
RUN_GAP_S = 60.0  # slots asked for further apart than this belong to the next run
Feed = Literal["sachet", "weather"]
SLOTS: dict[Feed, float] = {"sachet": SACHET_SLOT_S, "weather": WEATHER_SLOT_S}


class FetchError(RuntimeError):
    """The outside service couldn't be read (plain words). `status`: the HTTP status when it
    answered and refused (a 404 for one CAP), None when it didn't answer at all."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class TooLarge(FetchError):
    """The answer is over its cap: refused for good (not an outage to try again)."""


class BadRequest(FetchError):
    """JARVIS couldn't build the request (a local error, never the service's outage)."""


@dataclass(frozen=True)
class Fetched:
    status: int  # 200 or 304
    body: bytes
    etag: str | None = None


class OutsideClock:
    """Part B's outside time within one 5-minute run, in process (a restart forgets it).

    `deadline(feed)` is the monotonic time `feed` must finish by in this run: its own slot,
    counted from when it first asks, and never past the end of Part B's share (`SHARE_S` from the
    run's first ask). SACHET (more urgent) asks first; weather's slot is its own, so a SACHET
    outage or backlog costs weather nothing. The shared budget's real end is not visible to a
    job (`ticks.run_jobs` gives each job only what is left): INTEGRATION-B "Needs I1" proposes a
    way; until then the slots keep Part B inside 12 of the 19 s, and claims have a lease so a cut
    run loses nothing."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._run: float | None = None
        self._starts: dict[Feed, float] = {}

    def now(self) -> float:
        return self._clock()

    def deadline(self, feed: Feed) -> float:
        at = self._clock()
        if self._run is None or at - self._run >= RUN_GAP_S:
            self._run, self._starts = at, {}
        start = self._starts.setdefault(feed, at)
        return min(start + SLOTS[feed], self._run + SHARE_S)

    def left(self, deadline: float) -> float:
        return deadline - self._clock()


class Fetcher(Protocol):
    async def get(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        cap: int,
        timeout_s: float,
    ) -> Fetched: ...


def _check_url(url: str) -> httpx.URL:
    parsed = httpx.URL(url)
    if parsed.scheme != "https" or parsed.host not in ALLOWED_HOSTS:
        raise FetchError("That address isn't one JARVIS reads.")
    return parsed


async def _read(r: httpx.Response, cap: int) -> bytes:
    declared = r.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > cap:
        raise TooLarge("The answer was too large to use.")
    chunks: list[bytes] = []
    size = 0
    async for chunk in r.aiter_bytes():
        size += len(chunk)
        if size > cap:
            raise TooLarge("The answer was too large to use.")
        chunks.append(chunk)
    return b"".join(chunks)


def _build(
    client: httpx.AsyncClient,
    target: httpx.URL,
    params: Mapping[str, str] | None,
    headers: Mapping[str, str],
) -> httpx.Request:
    try:
        return client.build_request("GET", target, params=dict(params or {}), headers=headers)
    except (UnicodeError, ValueError, TypeError, httpx.InvalidURL) as exc:
        log.warning("helpers fetch not built", extra={"error": type(exc).__name__})
        raise BadRequest("JARVIS couldn't build that request.") from exc


class HttpFetcher:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport  # tests only (httpx.MockTransport); None: the network

    async def get(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        cap: int,
        timeout_s: float,
    ) -> Fetched:
        target = _check_url(url)
        limit = max(MIN_TIMEOUT_S, min(timeout_s, OUTSIDE_TIMEOUT_S))
        sent = {"User-Agent": USER_AGENT, **dict(headers or {})}
        try:
            async with asyncio.timeout(limit):
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(limit), follow_redirects=False, transport=self._transport
                ) as client:
                    request = _build(client, target, params, sent)
                    r = await client.send(request, stream=True)
                    try:
                        return await self._answer(r, cap)
                    finally:
                        await r.aclose()
        except TimeoutError as exc:
            log.warning("helpers fetch timed out", extra={"host": target.host})
            raise FetchError("The outside service took too long to answer.") from exc
        except httpx.HTTPError as exc:
            log.warning("helpers fetch failed", extra={"error": type(exc).__name__})
            raise FetchError("The outside service couldn't be reached.") from exc

    @staticmethod
    async def _answer(r: httpx.Response, cap: int) -> Fetched:
        etag = r.headers.get("etag")
        if r.status_code == 304:
            return Fetched(304, b"", etag)
        if r.status_code != 200:
            log.warning("helpers fetch refused", extra={"status": r.status_code})
            raise FetchError(f"The outside service answered {r.status_code}.", status=r.status_code)
        return Fetched(200, await _read(r, cap), etag)


__all__ = [
    "ALLOWED_HOSTS",
    "MIN_LEFT_S",
    "SACHET_SLOT_S",
    "SHARE_S",
    "WEATHER_SLOT_S",
    "BadRequest",
    "Feed",
    "FetchError",
    "Fetched",
    "Fetcher",
    "HttpFetcher",
    "OutsideClock",
    "TooLarge",
]
