# tests/test_connectors_youtube.py -- R4 D9: the owner's OWN YouTube channel and videos through the
# existing Google link (scope youtube.readonly). Read only; OFF until the scope is granted.
from __future__ import annotations

import httpx
import pytest
from google_fakes import GOOGLE_NOW, GOOGLE_UID, FakeGoogle, google_tokens
from pydantic import SecretStr

from jarvis.integrations.google import (
    YOUTUBE_SCOPE,
    GoogleConnector,
    GoogleNotConnected,
    GoogleQuotaExceeded,
)
from jarvis.integrations.vault import MemoryTokenStore
from jarvis.integrations.youtube import YouTubeNotGranted, YouTubeOwn
from jarvis.quota.ledger import YOUTUBE_UNITS, QuotaLedger, QuotaReached
from jarvis.storage.docs import MemoryDocs

API = "https://www.googleapis.com/youtube/v3"
CHANNEL = {
    "items": [
        {
            "id": "UC1234567890",
            "snippet": {"title": "Akash\nBuilds", "customUrl": "@akashbuilds"},
            "statistics": {"subscriberCount": "120", "videoCount": "7", "viewCount": "4500"},
            "contentDetails": {"relatedPlaylists": {"uploads": "UU1234567890"}},
        }
    ]
}


async def build(*, scopes: list[str] | None = None, linked: bool = True):
    fake = FakeGoogle()
    store = MemoryTokenStore()
    if linked:
        await store.put(GOOGLE_UID, google_tokens(scopes=scopes or [YOUTUBE_SCOPE]))
    conn = GoogleConnector(
        store,
        client_id="c",
        client_secret=SecretStr("s"),
        http=fake.client(),
        now=lambda: GOOGLE_NOW,
    )
    ledger = QuotaLedger(MemoryDocs())
    yt = YouTubeOwn(conn, ledger)
    yt.ledger = ledger  # type: ignore[attr-defined]  # test handle
    return yt, fake


async def test_status_reflects_the_granted_scope() -> None:
    yt, _ = await build()
    no, _ = await build(scopes=["https://www.googleapis.com/auth/gmail.readonly"])
    assert (await yt.status(GOOGLE_UID))["connected"] is True
    assert (await no.status(GOOGLE_UID))["connected"] is False
    assert (await no.status(GOOGLE_UID))["reason"] == "not_granted"


async def test_unlinked_google_is_reported_not_raised_by_status() -> None:
    yt, _ = await build(linked=False)
    assert (await yt.status(GOOGLE_UID)) == {"connected": False, "reason": "no_google"}


async def test_channel_returns_clean_own_channel_fields() -> None:
    yt, fake = await build()
    fake.on("GET", f"{API}/channels", httpx.Response(200, json=CHANNEL))
    ch = await yt.channel(GOOGLE_UID)
    assert ch.title == "Akash Builds" and ch.subscribers == 120 and ch.videos == 7
    assert fake.requests[0].url.params["mine"] == "true"


async def test_channel_without_the_scope_is_refused_before_any_call() -> None:
    yt, fake = await build(scopes=["https://www.googleapis.com/auth/gmail.readonly"])
    with pytest.raises(YouTubeNotGranted):
        await yt.channel(GOOGLE_UID)
    assert fake.requests == []


async def test_unlinked_google_raises_not_connected() -> None:
    yt, _ = await build(linked=False)
    with pytest.raises(GoogleNotConnected):
        await yt.channel(GOOGLE_UID)


async def test_videos_come_from_the_uploads_playlist_and_are_capped() -> None:
    yt, fake = await build()
    fake.on("GET", f"{API}/channels", httpx.Response(200, json=CHANNEL))
    items = [
        {
            "snippet": {
                "title": f"v{i}",
                "publishedAt": "2026-11-01T00:00:00Z",
                "resourceId": {"videoId": "abcdefghij" + str(i % 10)},
            },
        }
        for i in range(30)
    ]
    fake.on("GET", f"{API}/playlistItems", httpx.Response(200, json={"items": items}))
    vids = await yt.videos(GOOGLE_UID, limit=5)
    assert len(vids) == 5 and vids[0].video_id == "abcdefghij0"
    assert fake.sent("GET", "/playlistItems")[0].url.params["playlistId"] == "UU1234567890"


async def test_videos_with_bad_ids_are_dropped() -> None:
    yt, fake = await build()
    fake.on("GET", f"{API}/channels", httpx.Response(200, json=CHANNEL))
    items = [{"snippet": {"title": "x", "resourceId": {"videoId": "../../etc"}}}]
    fake.on("GET", f"{API}/playlistItems", httpx.Response(200, json={"items": items}))
    assert await yt.videos(GOOGLE_UID) == ()


async def test_no_channel_gives_an_empty_answer() -> None:
    yt, fake = await build()
    fake.on("GET", f"{API}/channels", httpx.Response(200, json={}))
    assert await yt.channel(GOOGLE_UID) is None
    assert await yt.videos(GOOGLE_UID) == ()


# ---- the slice-12 quota ledger (py-M5): every owner-token call is counted --------------------


def _items(n: int) -> dict:
    return {
        "items": [
            {"snippet": {"title": "t", "resourceId": {"videoId": "abcdefghij" + str(i % 10)}}}
            for i in range(n)
        ]
    }


async def used(yt: YouTubeOwn) -> int:
    return (await yt.ledger.use(YOUTUBE_UNITS)).used  # type: ignore[attr-defined]


async def test_channel_reserves_one_unit_and_videos_two() -> None:
    yt, fake = await build()
    fake.on("GET", f"{API}/channels", httpx.Response(200, json=CHANNEL))
    fake.on("GET", f"{API}/playlistItems", httpx.Response(200, json=_items(1)))
    await yt.channel(GOOGLE_UID)
    assert await used(yt) == 1
    await yt.videos(GOOGLE_UID)
    assert await used(yt) == 3  # 1 + 2


async def test_a_used_up_allowance_stops_the_call_before_google() -> None:
    yt, fake = await build()
    cap = yt.ledger.sku(YOUTUBE_UNITS).cap  # type: ignore[attr-defined]
    await yt.ledger.reserve(YOUTUBE_UNITS, cap)  # type: ignore[attr-defined]
    with pytest.raises(QuotaReached):
        await yt.channel(GOOGLE_UID)
    assert fake.requests == []


async def test_googles_quota_answer_closes_the_day() -> None:
    yt, fake = await build()
    body = {"error": {"code": 403, "message": "V", "errors": [{"reason": "quotaExceeded"}]}}
    fake.on("GET", f"{API}/channels", httpx.Response(403, json=body))
    with pytest.raises(GoogleQuotaExceeded):
        await yt.channel(GOOGLE_UID)
    with pytest.raises(QuotaReached):
        await yt.channel(GOOGLE_UID)


async def test_a_call_that_never_reached_google_gives_its_unit_back() -> None:
    yt, fake = await build()

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    yt._g.http = httpx.AsyncClient(transport=httpx.MockTransport(refuse))  # noqa: SLF001
    with pytest.raises(Exception):  # noqa: B017, PT011 - GoogleUncertain
        await yt.channel(GOOGLE_UID)
    assert await used(yt) == 0
