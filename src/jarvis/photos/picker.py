# src/jarvis/photos/picker.py
"""Google Photos Picker API client (R4 D8; developers.google.com/photos/picker).

    POST   photospicker.googleapis.com/v1/sessions            -> {id, pickerUri, expireTime,
                                                                  pollingConfig, mediaItemsSet}
    GET    .../v1/sessions/{id}                               -> same; mediaItemsSet true once the
                                                                  owner has finished picking
    GET    .../v1/mediaItems?sessionId=&pageSize=             -> {mediaItems: [{id, type,
                                                                  mediaFile:{baseUrl, mimeType}}]}
    DELETE .../v1/sessions/{id}
    GET    <baseUrl>=w1024-h1024  (Authorization: Bearer)     -> the picture, size-bounded

Scope `photospicker.mediaitems.readonly`. The Library API can no longer read a whole library, so
JARVIS only ever sees what the owner selected. Calls ride `GoogleConnector.request` (bearer, one
refresh, vendor text never leaves). Hosts are checked: the picker link must be on
photos.google.com and a base URL on googleusercontent.com, both https. A picture is streamed
and capped at MAX_IMAGE_BYTES before it is buffered, must be `image/jpeg`, and leaves here with
all metadata (EXIF/GPS) stripped (`photos.imaging`). R11.1 O6: a pick may hold up to 2,000 photos
(`photos_max_picked`); the list is read a page at a time (`list_page`) and no link is ever kept.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx

from jarvis.integrations.google import (
    NOT_CONNECTED_MSG,
    RECONNECT_MSG,
    GoogleAPIError,
    GoogleConnector,
    GoogleNotConnected,
)
from jarvis.integrations.vault import GoogleTokens
from jarvis.logging import get_logger
from jarvis.photos.errors import BAD_ANSWER, BAD_PICTURE, PickerError
from jarvis.photos.imaging import sanitise_jpeg
from jarvis.photos.models import PHOTOS_SCOPE, SESSION_ID, PickedItem, PickerSession

log = get_logger(__name__)

API = "https://photospicker.googleapis.com/v1"
PICKER_HOST = "photos.google.com"
IMAGE_HOST = re.compile(r"lh[0-9]+\.googleusercontent\.com")
SIZE_SUFFIX = "=w1024-h1024"
PICKER_MAX = 2000  # Google's own maximum for one pick ("values above 2000 are coerced to 2000")
PAGE_SIZE = 100  # mediaItems.list: Google's maximum page
MAX_TOKEN_CHARS = 2000
MAX_IMAGE_BYTES = 4_000_000
JPEG_TYPE = "image/jpeg"
STATUS_UNAUTHORIZED = 401
DOWNLOAD_TIMEOUT_S = 20.0
HTTP_OK = 200

GRANT_MSG = (
    "JARVIS has no permission to open the photos you pick yet. Open Integrations and press "
    "Grant next to 'Google Photos', then try again."
)


class PhotosNotGranted(RuntimeError):
    """The Google link exists but the Picker scope is not granted."""


def _https_host(url: object) -> str | None:
    if not isinstance(url, str):
        return None
    try:
        u = httpx.URL(url)
    except httpx.InvalidURL:
        return None
    if u.scheme != "https" or u.userinfo or u.port is not None:
        return None
    return u.host


def _session(raw: Any) -> PickerSession:
    if not isinstance(raw, dict):
        raise PickerError(BAD_ANSWER)
    sid, uri = raw.get("id"), raw.get("pickerUri")
    if not isinstance(sid, str) or not SESSION_ID.fullmatch(sid):
        raise PickerError(BAD_ANSWER)
    if uri is not None and _https_host(uri) != PICKER_HOST:
        raise PickerError(BAD_ANSWER)
    expires = raw.get("expireTime")
    return PickerSession(
        sid,
        uri or "",
        raw.get("mediaItemsSet") is True,
        expires if isinstance(expires, str) else "",
    )


def _item(raw: Any) -> PickedItem | None:
    if not isinstance(raw, dict) or raw.get("type") != "PHOTO":
        return None
    media = raw.get("mediaFile")
    if not isinstance(media, dict):
        return None
    base, mime, iid = media.get("baseUrl"), media.get("mimeType"), raw.get("id")
    host = _https_host(base)
    if host is None or not IMAGE_HOST.fullmatch(host):
        return None
    if not isinstance(iid, str) or not isinstance(mime, str) or not mime.startswith("image/"):
        return None
    return PickedItem(iid[:200], mime, str(base))


def _check_headers(r: httpx.Response) -> None:
    if r.headers.get("content-type", "").split(";")[0].strip().lower() != JPEG_TYPE:
        raise PickerError(BAD_PICTURE)
    declared = r.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_IMAGE_BYTES:
        raise PickerError(BAD_PICTURE)


class PickerClient:
    def __init__(self, google: GoogleConnector, *, max_picked: int = PICKER_MAX) -> None:
        self._g = google
        self._max = max(1, min(int(max_picked), PICKER_MAX))

    async def status(self, uid: str) -> dict[str, Any]:
        st = await self._g.status(uid)
        if not st["connected"] or st["needs_reconnect"]:
            return {"connected": False, "reason": "no_google"}
        if PHOTOS_SCOPE not in st["scopes"]:
            return {"connected": False, "reason": "not_granted"}
        return {"connected": True, "reason": None}

    async def _require(self, uid: str) -> None:
        st = await self._g.status(uid)
        if not st["connected"] or st["needs_reconnect"]:
            raise GoogleNotConnected(RECONNECT_MSG if st["needs_reconnect"] else NOT_CONNECTED_MSG)
        if PHOTOS_SCOPE not in st["scopes"]:
            raise PhotosNotGranted(GRANT_MSG)

    @staticmethod
    def _sid(session_id: str) -> str:
        if not isinstance(session_id, str) or not SESSION_ID.fullmatch(session_id):
            raise PickerError(BAD_ANSWER)
        return session_id

    async def create_session(self, uid: str, max_items: int | None = None) -> PickerSession:
        """A new pick of at most `max_items` photos (the owner's `photos_max_picked`; never more
        than Google's 2,000)."""
        await self._require(uid)
        limit = max(1, min(int(max_items or self._max), PICKER_MAX))
        body = {"pickingConfig": {"maxItemCount": str(limit)}}  # int64 travels as a string
        raw = await self._g.request(uid, "POST", f"{API}/sessions", json=body, send_once=True)
        return _session(raw)

    async def get_session(self, uid: str, session_id: str) -> PickerSession:
        sid = self._sid(session_id)
        await self._require(uid)
        return _session(await self._g.request(uid, "GET", f"{API}/sessions/{sid}"))

    async def list_page(
        self, uid: str, session_id: str, token: str = ""
    ) -> tuple[tuple[PickedItem, ...], str]:
        """One page of what the owner picked (photos only) and the next page's token ("" at the
        end). The links in it are fresh: Google's expire after about an hour, so an import asks
        for the page again instead of keeping them (R11.1 O6)."""
        sid = self._sid(session_id)
        await self._require(uid)
        params: dict[str, Any] = {"sessionId": sid, "pageSize": PAGE_SIZE}
        if token:
            if not isinstance(token, str) or len(token) > MAX_TOKEN_CHARS:
                raise PickerError(BAD_ANSWER)
            params["pageToken"] = token
        raw = await self._g.request(uid, "GET", f"{API}/mediaItems", params=params)
        rows = raw.get("mediaItems") if isinstance(raw, dict) else None
        found = (_item(r) for r in rows[:PAGE_SIZE]) if isinstance(rows, list) else ()
        nxt = raw.get("nextPageToken") if isinstance(raw, dict) else None
        ok = isinstance(nxt, str) and 0 < len(nxt) <= MAX_TOKEN_CHARS
        return tuple(i for i in found if i is not None), (str(nxt) if ok else "")

    async def list_items(self, uid: str, session_id: str) -> tuple[PickedItem, ...]:
        """The first page only (kept for callers that want a quick look)."""
        items, _ = await self.list_page(uid, session_id)
        return items

    async def download(self, uid: str, item: PickedItem) -> bytes:
        """One picture, size-capped while streaming, one refresh on 401, metadata stripped."""
        await self._require(uid)
        url = item.base_url + SIZE_SUFFIX
        status, data = await self._fetch(url, await self._g.access_token(uid))
        if status == STATUS_UNAUTHORIZED:
            status, data = await self._fetch(url, await self._renew(uid))
        if status != HTTP_OK:
            raise PickerError(BAD_PICTURE)
        return await asyncio.to_thread(sanitise_jpeg, data)

    async def _renew(self, uid: str) -> str:
        """A fresh access token (the stored one was refused). `GoogleConnector.request` only
        does this for JSON calls, so the photo stream reuses its refresh step."""
        tokens = await self._g._load(uid)  # noqa: SLF001 - same package family; see INTEGRATION.md
        if not isinstance(tokens, GoogleTokens):
            raise GoogleNotConnected(RECONNECT_MSG)
        return await self._g._refresh(uid, tokens)  # noqa: SLF001

    async def _fetch(self, url: str, token: str) -> tuple[int, bytes]:
        """(status, body). The body is only read for a 200 `image/jpeg` that fits the cap."""
        try:
            async with self._g.http.stream(
                "GET",
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=DOWNLOAD_TIMEOUT_S,
                follow_redirects=False,
            ) as r:
                if r.status_code != HTTP_OK:
                    return r.status_code, b""
                _check_headers(r)
                buf = bytearray()
                async for chunk in r.aiter_bytes():
                    buf += chunk
                    if len(buf) > MAX_IMAGE_BYTES:
                        raise PickerError(BAD_PICTURE)
                return r.status_code, bytes(buf)
        except httpx.HTTPError as exc:
            log.warning("photo download failed", extra={"reason": type(exc).__name__})
            raise PickerError(BAD_PICTURE) from None

    async def delete_session(self, uid: str, session_id: str) -> None:
        """Best effort: Google expires sessions on its own."""
        try:
            await self._g.request(uid, "DELETE", f"{API}/sessions/{self._sid(session_id)}")
        except (GoogleAPIError, GoogleNotConnected, PickerError) as exc:
            log.warning("picker session cleanup failed", extra={"reason": type(exc).__name__})


__all__ = ["PAGE_SIZE", "PICKER_MAX", "PhotosNotGranted", "PickerClient", "PickerError"]
