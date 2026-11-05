# tests/test_photos_picker.py -- R4 D8: the Google Photos Picker API flow (the owner selects; the
# Library API can no longer read the whole library). Scope photospicker.mediaitems.readonly.
from __future__ import annotations

import httpx
import pytest
from google_fakes import GOOGLE_NOW, GOOGLE_UID, FakeGoogle, google_tokens
from pydantic import SecretStr

from jarvis.integrations.google import GoogleConnector, GoogleNotConnected
from jarvis.integrations.vault import MemoryTokenStore
from jarvis.photos.models import PHOTOS_SCOPE
from jarvis.photos.picker import (
    MAX_PICKED,
    PhotosNotGranted,
    PickerClient,
    PickerError,
)

API = "https://photospicker.googleapis.com/v1"
SESSION = {
    "id": "sess-abc_123",
    "pickerUri": "https://photos.google.com/picker/xyz",
    "pollingConfig": {"pollInterval": "5s", "timeoutIn": "1800s"},
    "expireTime": "2026-11-05T13:00:00Z",
    "mediaItemsSet": False,
}


async def build(*, scopes: list[str] | None = None, linked: bool = True):
    fake = FakeGoogle()
    store = MemoryTokenStore()
    if linked:
        await store.put(GOOGLE_UID, google_tokens(scopes=scopes or [PHOTOS_SCOPE]))
    conn = GoogleConnector(
        store,
        client_id="c",
        client_secret=SecretStr("s"),
        http=fake.client(),
        now=lambda: GOOGLE_NOW,
    )
    return PickerClient(conn), fake


def item(i: int, **over: object) -> dict:
    base = {
        "id": f"m{i}",
        "type": "PHOTO",
        "mediaFile": {
            "baseUrl": f"https://lh3.googleusercontent.com/pw/{i}",
            "mimeType": "image/jpeg",
            "filename": f"IMG_{i}.jpg",
        },
    }
    base.update(over)
    return base


async def test_status_is_off_without_the_photos_scope() -> None:
    off, _ = await build(scopes=["https://www.googleapis.com/auth/gmail.readonly"])
    on, _ = await build()
    assert (await off.status(GOOGLE_UID))["connected"] is False
    assert (await on.status(GOOGLE_UID))["connected"] is True


async def test_create_session_returns_the_picker_link() -> None:
    picker, fake = await build()
    fake.on("POST", f"{API}/sessions", httpx.Response(200, json=SESSION))
    s = await picker.create_session(GOOGLE_UID)
    assert s.id == "sess-abc_123" and s.picker_uri.startswith("https://photos.google.com/")
    assert s.ready is False


async def test_a_picker_link_to_another_host_is_refused() -> None:
    picker, fake = await build()
    bad = {**SESSION, "pickerUri": "https://evil.example/picker"}
    fake.on("POST", f"{API}/sessions", httpx.Response(200, json=bad))
    with pytest.raises(PickerError):
        await picker.create_session(GOOGLE_UID)


async def test_without_the_scope_nothing_is_called() -> None:
    picker, fake = await build(scopes=["https://www.googleapis.com/auth/gmail.readonly"])
    with pytest.raises(PhotosNotGranted):
        await picker.create_session(GOOGLE_UID)
    assert fake.requests == []


async def test_without_google_it_says_not_connected() -> None:
    picker, _ = await build(linked=False)
    with pytest.raises(GoogleNotConnected):
        await picker.create_session(GOOGLE_UID)


async def test_session_state_reports_when_the_owner_has_picked() -> None:
    picker, fake = await build()
    fake.on(
        "GET",
        f"{API}/sessions/sess-abc_123",
        httpx.Response(200, json={**SESSION, "mediaItemsSet": True}),
    )
    assert (await picker.get_session(GOOGLE_UID, "sess-abc_123")).ready is True


async def test_session_id_is_validated_before_it_reaches_a_url() -> None:
    picker, fake = await build()
    with pytest.raises(PickerError):
        await picker.get_session(GOOGLE_UID, "../../v1/mediaItems")
    assert fake.requests == []


async def test_only_photos_are_listed_and_capped() -> None:
    picker, fake = await build()
    items = [item(i) for i in range(MAX_PICKED + 10)] + [item(99, type="VIDEO")]
    fake.on("GET", f"{API}/mediaItems", httpx.Response(200, json={"mediaItems": items}))
    got = await picker.list_items(GOOGLE_UID, "sess-abc_123")
    assert len(got) == MAX_PICKED and all(g.mime_type == "image/jpeg" for g in got)
    assert fake.requests[0].url.params["sessionId"] == "sess-abc_123"


async def test_items_with_a_foreign_base_url_are_dropped() -> None:
    picker, fake = await build()
    evil = item(1)
    evil["mediaFile"]["baseUrl"] = "https://evil.example/a"
    fake.on("GET", f"{API}/mediaItems", httpx.Response(200, json={"mediaItems": [evil, item(2)]}))
    got = await picker.list_items(GOOGLE_UID, "sess-abc_123")
    assert [g.id for g in got] == ["m2"]


async def test_download_asks_for_a_bounded_size_with_the_owners_token() -> None:
    picker, fake = await build()
    fake.on("GET", f"{API}/mediaItems", httpx.Response(200, json={"mediaItems": [item(1)]}))
    (it,) = await picker.list_items(GOOGLE_UID, "sess-abc_123")
    fake.on(
        "GET",
        "https://lh3.googleusercontent.com/pw/1=w1024-h1024",
        httpx.Response(200, content=b"\xff\xd8\xffJPEG"),
    )
    data = await picker.download(GOOGLE_UID, it)
    assert data.startswith(b"\xff\xd8\xff")
    assert fake.requests[-1].headers["Authorization"].startswith("Bearer ")


async def test_download_refuses_something_that_is_not_a_jpeg_or_is_too_big() -> None:
    picker, fake = await build()
    fake.on("GET", f"{API}/mediaItems", httpx.Response(200, json={"mediaItems": [item(1)]}))
    (it,) = await picker.list_items(GOOGLE_UID, "sess-abc_123")
    url = "https://lh3.googleusercontent.com/pw/1=w1024-h1024"
    fake.on("GET", url, httpx.Response(200, content=b"<html>"))
    with pytest.raises(PickerError):
        await picker.download(GOOGLE_UID, it)


async def test_delete_session_is_best_effort() -> None:
    picker, fake = await build()
    fake.on("DELETE", f"{API}/sessions/sess-abc_123", httpx.Response(500))
    await picker.delete_session(GOOGLE_UID, "sess-abc_123")  # must not raise
