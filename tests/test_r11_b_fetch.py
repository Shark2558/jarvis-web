# tests/test_r11_b_fetch.py -- R11 Part B's one outbound path (docs/plans/r11-free-helpers.md D20)
# on httpx's MockTransport (no network): only https to Open-Meteo and SACHET, no redirect followed,
# the body capped (declared or streamed), 304 kept, any other status, a timeout or a transport
# error a plain-word FetchError; the query and headers it sends.
from __future__ import annotations

import asyncio

import httpx
import pytest

from jarvis.helpers.house.fetch import ALLOWED_HOSTS, FetchError, HttpFetcher, TooLarge
from jarvis.helpers.sources import OPEN_METEO_FORECAST_URL, SACHET_CAP_URL, SACHET_RSS_URL

RSS = SACHET_RSS_URL.format(feed="kerala")


def _fetcher(handler: object) -> HttpFetcher:
    return HttpFetcher(httpx.MockTransport(handler))  # type: ignore[arg-type]


def test_only_the_two_fixed_hosts() -> None:
    assert ALLOWED_HOSTS == {"api.open-meteo.com", "sachet.ndma.gov.in"}


async def test_a_200_with_its_etag_params_and_headers() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"<rss/>", headers={"ETag": '"abc"'})

    got = await _fetcher(handler).get(RSS, headers={"If-None-Match": '"old"'}, cap=100, timeout_s=8)
    assert (got.status, got.body, got.etag) == (200, b"<rss/>", '"abc"')
    (req,) = seen
    assert req.headers["If-None-Match"] == '"old"' and "JARVIS" in req.headers["User-Agent"]
    await _fetcher(handler).get(
        SACHET_CAP_URL, params={"identifier": "123456"}, cap=100, timeout_s=8
    )
    assert seen[1].url.params["identifier"] == "123456"


async def test_304_is_kept_and_other_statuses_and_redirects_fail() -> None:
    got = await _fetcher(lambda r: httpx.Response(304, headers={"ETag": '"v"'})).get(
        RSS, cap=10, timeout_s=8
    )
    assert (got.status, got.body, got.etag) == (304, b"", '"v"')
    for answer in (
        httpx.Response(500),
        httpx.Response(302, headers={"Location": "https://evil.example/x"}),
    ):
        with pytest.raises(FetchError):
            await _fetcher(lambda r, a=answer: a).get(OPEN_METEO_FORECAST_URL, cap=10, timeout_s=8)


async def test_the_body_is_capped_declared_or_streamed() -> None:
    declared = _fetcher(
        lambda r: httpx.Response(200, content=b"x" * 50, headers={"Content-Length": "5000"})
    )
    with pytest.raises(TooLarge):
        await declared.get(RSS, cap=100, timeout_s=8)
    streamed = _fetcher(lambda r: httpx.Response(200, content=b"x" * 500))
    with pytest.raises(TooLarge):
        await streamed.get(RSS, cap=100, timeout_s=8)


async def test_other_hosts_plain_http_timeouts_and_transport_errors_fail() -> None:
    ok = _fetcher(lambda r: httpx.Response(200, content=b"{}"))
    for url in ("https://evil.example/x", "http://api.open-meteo.com/v1/forecast"):
        with pytest.raises(FetchError):
            await ok.get(url, cap=10, timeout_s=8)

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with pytest.raises(FetchError):
        await _fetcher(boom).get(RSS, cap=10, timeout_s=8)

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(2)
        return httpx.Response(200)

    with pytest.raises(FetchError):
        await _fetcher(slow).get(RSS, cap=10, timeout_s=0.5)
