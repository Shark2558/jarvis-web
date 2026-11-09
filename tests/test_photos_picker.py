# tests/test_photos_picker.py -- R4 D8: the Google Photos Picker API flow (the owner selects; the
# Library API can no longer read the whole library). Scope photospicker.mediaitems.readonly.
from __future__ import annotations

import logging
import struct

import httpx
import pytest
from google_fakes import GOOGLE_NOW, GOOGLE_UID, FakeGoogle, google_tokens
from pydantic import SecretStr

from jarvis.integrations.google import GoogleConnector, GoogleNotConnected
from jarvis.integrations.vault import MemoryTokenStore
from jarvis.photos.models import PHOTOS_SCOPE
from jarvis.photos.picker import (
    MAX_IMAGE_BYTES,
    MAX_PICKED,
    PhotosNotGranted,
    PickerClient,
    PickerError,
)

IMG_URL = "https://lh3.googleusercontent.com/pw/1=w1024-h1024"
TOKEN_URL = "https://oauth2.googleapis.com/token"
VALID_JPEG = (
    b"\xff\xd8\xff\xe1\x00\x0aExifGPS!"  # an EXIF segment the sanitiser must remove
    + b"\xff\xdb\x00\x43\x00"
    + bytes(64)
    + b"\xff\xc0"
    + struct.pack(">HBHHB", 11, 8, 8, 8, 1)
    + b"\x01\x11\x00"
    + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
    + b"\x12\x34"
    + b"\xff\xd9"
)
JPEG_HEADERS = {"content-type": "image/jpeg"}
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


async def one_item(picker, fake):
    fake.on("GET", f"{API}/mediaItems", httpx.Response(200, json={"mediaItems": [item(1)]}))
    (it,) = await picker.list_items(GOOGLE_UID, "sess-abc_123")
    return it


async def test_download_asks_for_a_bounded_size_with_the_owners_token_and_strips_exif() -> None:
    picker, fake = await build()
    it = await one_item(picker, fake)
    fake.on("GET", IMG_URL, httpx.Response(200, content=VALID_JPEG, headers=JPEG_HEADERS))
    data = await picker.download(GOOGLE_UID, it)
    assert data.startswith(b"\xff\xd8\xff") and b"Exif" not in data
    assert fake.requests[-1].headers["Authorization"].startswith("Bearer ")


@pytest.mark.parametrize(
    "resp",
    [
        httpx.Response(200, content=b"<html>", headers=JPEG_HEADERS),
        httpx.Response(200, content=VALID_JPEG, headers={"content-type": "text/html"}),
        httpx.Response(200, content=VALID_JPEG),
        httpx.Response(404),
        httpx.Response(302, headers={"location": "https://evil.example/x"}),
    ],
)
async def test_download_refuses_what_is_not_a_clean_jpeg_answer(resp: httpx.Response) -> None:
    picker, fake = await build()
    it = await one_item(picker, fake)
    fake.on("GET", IMG_URL, resp)
    with pytest.raises(PickerError):
        await picker.download(GOOGLE_UID, it)


async def test_a_declared_content_length_over_the_cap_is_refused_without_reading() -> None:
    picker, fake = await build()
    it = await one_item(picker, fake)
    headers = {**JPEG_HEADERS, "content-length": str(MAX_IMAGE_BYTES + 1)}

    class Boom(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise AssertionError("body must not be read")
            yield b""

    fake.on("GET", IMG_URL, httpx.Response(200, headers=headers, stream=Boom()))
    with pytest.raises(PickerError):
        await picker.download(GOOGLE_UID, it)


async def test_a_body_that_outgrows_the_cap_is_aborted_while_streaming() -> None:
    picker, fake = await build()
    it = await one_item(picker, fake)
    pulled = 0

    class Endless(httpx.AsyncByteStream):
        async def __aiter__(self):
            nonlocal pulled
            for _ in range(10_000):
                pulled += 1
                yield b"\xff" * 100_000

    fake.on("GET", IMG_URL, httpx.Response(200, headers=JPEG_HEADERS, stream=Endless()))
    with pytest.raises(PickerError):
        await picker.download(GOOGLE_UID, it)
    assert pulled <= MAX_IMAGE_BYTES // 100_000 + 2


async def test_an_expired_token_on_download_is_refreshed_once_and_retried() -> None:
    picker, fake = await build()
    it = await one_item(picker, fake)
    fake.on(
        "GET",
        IMG_URL,
        httpx.Response(401),
        httpx.Response(200, content=VALID_JPEG, headers=JPEG_HEADERS),
    )
    fake.on(
        "POST", TOKEN_URL, httpx.Response(200, json={"access_token": "new", "expires_in": 3600})
    )
    assert (await picker.download(GOOGLE_UID, it)).startswith(b"\xff\xd8")
    assert fake.requests[-1].headers["Authorization"] == "Bearer new"


async def test_a_second_401_gives_up_with_plain_words() -> None:
    picker, fake = await build()
    it = await one_item(picker, fake)
    fake.on("GET", IMG_URL, httpx.Response(401))
    fake.on(
        "POST", TOKEN_URL, httpx.Response(200, json={"access_token": "new", "expires_in": 3600})
    )
    with pytest.raises(PickerError):
        await picker.download(GOOGLE_UID, it)


async def test_an_oversized_picture_is_refused_by_the_dimension_guard() -> None:
    picker, fake = await build()
    it = await one_item(picker, fake)
    wide = VALID_JPEG.replace(struct.pack(">HH", 8, 8), struct.pack(">HH", 8, 5000))
    fake.on("GET", IMG_URL, httpx.Response(200, content=wide, headers=JPEG_HEADERS))
    with pytest.raises(PickerError):
        await picker.download(GOOGLE_UID, it)


@pytest.mark.parametrize(
    "host",
    [
        "evil.googleusercontent.com",
        "lh3.googleusercontent.com.evil.example",
        "lhx.googleusercontent.com",
    ],
)
async def test_only_lh_n_image_hosts_are_accepted(host: str) -> None:
    picker, fake = await build()
    bad = item(1)
    bad["mediaFile"]["baseUrl"] = f"https://{host}/a"
    fake.on("GET", f"{API}/mediaItems", httpx.Response(200, json={"mediaItems": [bad]}))
    assert await picker.list_items(GOOGLE_UID, "sess-abc_123") == ()


async def test_session_is_created_with_a_max_item_count() -> None:
    picker, fake = await build()
    fake.on("POST", f"{API}/sessions", httpx.Response(200, json=SESSION))
    await picker.create_session(GOOGLE_UID)
    import json as _json

    body = _json.loads(fake.requests[0].content)
    assert body == {"pickingConfig": {"maxItemCount": str(MAX_PICKED)}}


async def test_the_token_and_base_url_never_reach_the_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    picker, fake = await build()
    it = await one_item(picker, fake)
    fake.on("GET", IMG_URL, httpx.Response(500))
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(PickerError):
            await picker.download(GOOGLE_UID, it)
    assert "old-access" not in caplog.text and "googleusercontent" not in caplog.text


async def test_delete_session_is_best_effort() -> None:
    picker, fake = await build()
    fake.on("DELETE", f"{API}/sessions/sess-abc_123", httpx.Response(500))
    await picker.delete_session(GOOGLE_UID, "sess-abc_123")  # must not raise
