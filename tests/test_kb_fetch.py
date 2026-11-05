# tests/test_kb_fetch.py -- R2 C: fetching a saved link's page text, only through WebAllowance + the
# Tavily door (reserve -> extract -> settle / refund / latch), with the private-URL guard.
from __future__ import annotations

import pytest
from kb_fakes import Rig, build_rig

from jarvis.kb.fetch import MAX_FETCHED, fetch_page
from jarvis.kb.models import MAX_EXCERPT, NotesError

URL = "https://example.com/story"


async def credits(r: Rig) -> int:
    return (await r.allowance.usage()).credits


async def test_a_fetch_spends_exactly_one_credit_and_returns_cleaned_text() -> None:
    r = build_rig()
    r.fake.pages[URL] = "Headline of the story\n\nBody \x00text​ here.\n" + "x" * 9000
    page = await fetch_page(r.web, URL)
    assert page.title == "Headline of the story"
    assert "\x00" not in page.excerpt and "​" not in page.excerpt
    assert len(page.excerpt) <= MAX_EXCERPT and "Body text here." in page.excerpt
    assert await credits(r) == 1
    assert [b["urls"] for b in r.fake.bodies("/extract")] == [[URL]]
    assert page.left == 899


async def test_a_failed_read_refunds_and_says_so_in_plain_words() -> None:
    r = build_rig()  # the fake has no such page: "failed_results" with vendor text
    with pytest.raises(NotesError) as e:
        await fetch_page(r.web, URL)
    assert e.value.code == "fetch_failed" and "vendor" not in e.value.detail.lower()
    assert await credits(r) == 0


async def test_a_vendor_error_refunds() -> None:
    r = build_rig()
    r.fake.status = 500
    with pytest.raises(NotesError) as e:
        await fetch_page(r.web, URL)
    assert e.value.code == "fetch_failed" and await credits(r) == 0


async def test_vendor_credits_gone_latches_the_month() -> None:
    r = build_rig()
    r.fake.status = 432
    with pytest.raises(NotesError) as e:
        await fetch_page(r.web, URL)
    assert e.value.code == "allowance" and e.value.status == 409
    assert await credits(r) == r.allowance.cap


async def test_an_used_up_month_sends_nothing() -> None:
    r = build_rig()
    await r.allowance.reserve(900, kind="read")
    with pytest.raises(NotesError) as e:
        await fetch_page(r.web, URL)
    assert e.value.code == "allowance" and r.fake.requests == []


async def test_no_web_service_means_web_off() -> None:
    with pytest.raises(NotesError) as e:
        await fetch_page(None, URL)
    assert e.value.code == "web_off" and e.value.status == 409


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/u?email=ravi@example.com",
        "https://example.com/call/9845012345",
        "https://example.com/p/ABCDE1234F",
        "https://example.com/?card=4111111111111111",
    ],
)
async def test_urls_carrying_private_data_are_never_sent(url: str) -> None:
    r = build_rig()
    with pytest.raises(NotesError) as e:
        await fetch_page(r.web, url)
    assert e.value.code == "bad_url" and e.value.reason == "private"
    assert r.fake.requests == [] and await credits(r) == 0


@pytest.mark.parametrize(
    "url", ["http://example.com/", "javascript:alert(1)", "https://u:p@example.com/"]
)
async def test_non_https_or_userinfo_links_are_never_sent(url: str) -> None:
    r = build_rig()
    with pytest.raises(NotesError) as e:
        await fetch_page(r.web, url)
    assert e.value.code == "bad_url" and r.fake.requests == []


async def test_excerpt_cap_constant_matches_the_model() -> None:
    assert MAX_FETCHED >= MAX_EXCERPT
