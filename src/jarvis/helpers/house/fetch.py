# src/jarvis/helpers/house/fetch.py
"""Part B's one outbound path (docs/plans/r11-free-helpers.md D20, `helpers.sources`).

`HttpFetcher.get(url, params=, headers=, cap=, timeout_s=)` is a plain GET with `httpx`:
- only to the two fixed hosts (`ALLOWED_HOSTS`: Open-Meteo and NDMA SACHET), https only, no
  redirects followed, so a link inside a feed can never send JARVIS anywhere else (the CAP URL is
  always built from `sources.SACHET_CAP_URL` and a digits-only identifier);
- inside `min(timeout_s, OUTSIDE_TIMEOUT_S)` seconds in all (8 s at most);
- the body read in chunks and refused past `cap` bytes (a declared `Content-Length` too);
- 304 (an `If-None-Match` hit) answers an empty body; any other non-200 is a `FetchError`.
Errors carry plain words; the log gets the class name and the status only, never a URL query.
Tests use a fake with the same `get` (tests/r11_fakes_b.py).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

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


class FetchError(RuntimeError):
    """The outside service couldn't be read (plain words)."""


class TooLarge(FetchError):
    """The answer is over its cap: refused for good (not an outage to try again)."""


@dataclass(frozen=True)
class Fetched:
    status: int  # 200 or 304
    body: bytes
    etag: str | None = None


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
                    async with client.stream(
                        "GET", target, params=dict(params or {}), headers=sent
                    ) as r:
                        return await self._answer(r, cap)
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
            raise FetchError(f"The outside service answered {r.status_code}.")
        return Fetched(200, await _read(r, cap), etag)


__all__ = ["ALLOWED_HOSTS", "FetchError", "Fetched", "Fetcher", "HttpFetcher", "TooLarge"]
