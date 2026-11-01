# tests/test_web_tavily.py — slice 10 B: the Tavily adapter behind the SearchProvider port. Fake
# transport only (no network): request shape, bearer auth, strict response validation, size caps,
# the overall deadline and owner-friendly errors that never echo vendor text or the key.
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr
from web_fakes import FakeTavily, hit

from jarvis.web.ports import SearchProvider, WebError
from jarvis.web.tavily import MAX_RESPONSE_BYTES, TavilyProvider

KEY = "tvly-test-secret-key"


def _provider(fake: FakeTavily, **kw: object) -> TavilyProvider:
    return TavilyProvider(SecretStr(KEY), http=fake.client(), **kw)  # type: ignore[arg-type]


async def test_it_implements_the_port() -> None:
    assert isinstance(_provider(FakeTavily()), SearchProvider)


async def test_search_sends_bearer_auth_and_a_basic_one_credit_request() -> None:
    fake = FakeTavily()
    page = await _provider(fake).search("RBI repo rate", max_results=3, topic="news", days=7)
    [req] = fake.requests
    assert req.method == "POST" and str(req.url) == "https://api.tavily.com/search"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(req.content)
    assert "api_key" not in body  # the key travels only in the header
    assert body["query"] == "RBI repo rate" and body["max_results"] == 3
    assert body["search_depth"] == "basic" and body["topic"] == "news"
    assert body["time_range"] == "week"
    assert "auto_parameters" not in body  # may silently switch to advanced (2 credits)
    for off in ("include_answer", "include_raw_content", "include_images", "include_favicon"):
        assert body[off] is False
    assert body["include_usage"] is True
    assert [h.url for h in page.hits] == [f"https://example.com/page{i}" for i in (1, 2, 3)]
    assert page.hits[0].title == "Result 1" and page.hits[0].content == "Snippet number 1."
    assert page.hits[0].published == "2026-10-30"
    assert page.credits == 1


@pytest.mark.parametrize(
    ("days", "expected"), [(None, None), (1, "day"), (3, "week"), (30, "month"), (200, "year")]
)
async def test_days_map_to_time_range(days: int | None, expected: str | None) -> None:
    fake = FakeTavily()
    await _provider(fake).search("q", max_results=5, topic="general", days=days)
    body = json.loads(fake.requests[0].content)
    assert body.get("time_range") == expected


async def test_bad_result_items_are_dropped_and_fields_are_type_checked() -> None:
    fake = FakeTavily()
    fake.results = [
        hit(1),
        "junk",  # type: ignore[list-item]
        {"title": 7, "url": "https://ok.example/2", "content": None},
        {"title": "no url"},
        hit(3, published_date=12345),
    ]
    page = await _provider(fake).search("q", max_results=5, topic="general", days=None)
    assert [h.url for h in page.hits] == [
        "https://example.com/page1",
        "https://ok.example/2",
        "https://example.com/page3",
    ]
    assert page.hits[1].title == "" and page.hits[1].content == ""
    assert page.hits[2].published is None


@pytest.mark.parametrize(
    "raw",
    [b"not json", b"[]", b'{"results": "nope"}', b'{"query": "x"}', b"\xff\xfe"],
)
async def test_an_unreadable_search_response_is_an_error(raw: bytes) -> None:
    fake = FakeTavily()
    fake.raw_search = raw
    with pytest.raises(WebError, match="unreadable"):
        await _provider(fake).search("q", max_results=5, topic="general", days=None)


async def test_an_oversized_response_is_refused() -> None:
    fake = FakeTavily()
    fake.raw_search = b'{"results": [' + b" " * (MAX_RESPONSE_BYTES + 10) + b"]}"
    with pytest.raises(WebError, match="too large"):
        await _provider(fake).search("q", max_results=5, topic="general", days=None)


@pytest.mark.parametrize(
    ("status", "words"),
    [
        (400, "rejected the request"),
        (401, "key"),
        (403, "key"),
        (422, "rejected the request"),
        (429, "too many"),
        (432, "used up"),
        (433, "pay-as-you-go"),
        (434, "busy"),
        (500, "unavailable"),
        (503, "unavailable"),
        (302, "unexpected"),
    ],
)
async def test_errors_are_plain_and_never_echo_vendor_text_or_the_key(
    status: int, words: str
) -> None:
    fake = FakeTavily()
    fake.status = status
    fake.body = b'{"detail": "vendor secret detail tvly-test-secret-key"}'
    with pytest.raises(WebError) as e:
        await _provider(fake).search("q", max_results=5, topic="general", days=None)
    msg = str(e.value)
    assert words in msg.lower()
    assert "vendor" not in msg and KEY not in msg and "$" not in msg


async def test_transport_failure_and_deadline_are_plain_errors() -> None:
    def boom(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failed for api.tavily.com")

    p = TavilyProvider(SecretStr(KEY), http=httpx.AsyncClient(transport=httpx.MockTransport(boom)))
    with pytest.raises(WebError, match="reach Tavily"):
        await p.search("q", max_results=5, topic="general", days=None)

    async def slow(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200, json={"results": []})

    p = TavilyProvider(
        SecretStr(KEY),
        http=httpx.AsyncClient(transport=httpx.MockTransport(slow)),
        deadline_s=0.05,
    )
    with pytest.raises(WebError, match="too long"):
        await p.search("q", max_results=5, topic="general", days=None)


async def test_extract_reads_one_url_as_text() -> None:
    fake = FakeTavily()
    fake.pages["https://example.com/page1"] = "Hello page"
    page = await _provider(fake).extract("https://example.com/page1")
    [req] = fake.requests
    assert str(req.url) == "https://api.tavily.com/extract"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(req.content)
    assert body["urls"] == ["https://example.com/page1"]
    assert body["extract_depth"] == "basic" and body["format"] == "text"
    assert body["include_images"] is False and body["include_usage"] is True
    assert 1 <= body["timeout"] <= 60
    assert page.text == "Hello page" and page.credits == 1 and page.ok


async def test_a_failed_extraction_is_reported_without_vendor_text() -> None:
    fake = FakeTavily()
    page = await _provider(fake).extract("https://example.com/missing")
    assert not page.ok and page.text == ""
    assert "vendor" not in page.reason and page.reason


async def test_extract_validates_its_response() -> None:
    fake = FakeTavily()
    fake.status = None

    def odd(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [{"url": 3, "raw_content": ["x"]}]})

    p = TavilyProvider(SecretStr(KEY), http=httpx.AsyncClient(transport=httpx.MockTransport(odd)))
    page = await p.extract("https://example.com/a")
    assert not page.ok


async def test_aclose_closes_only_a_client_it_owns() -> None:
    fake = FakeTavily()
    shared = fake.client()
    p = TavilyProvider(SecretStr(KEY), http=shared)
    await p.aclose()
    assert not shared.is_closed  # the caller's client stays open
    own = TavilyProvider(SecretStr(KEY))
    await own.aclose()
    assert own.http.is_closed
