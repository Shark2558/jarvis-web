# src/jarvis/integrations/youtube.py
"""The owner's OWN YouTube channel and uploads (R4 D9; Layer 6), through the existing Google link
(`GoogleConnector`, scope youtube.readonly). Read only. Not the slice-12 search tool
(`jarvis.media`, the `youtube_*` row): that searches YouTube; this reads the owner's account.

channels.list (mine=true) and playlistItems.list cost 1 quota unit each (developers.google.com/
youtube/v3/determine_quota_cost); each call is sent once (`send_once`), so nothing is retried at
the owner's quota. Every field is type-checked and cut to one clean line; titles are other
people's words as far as the model is concerned (the tools fence them).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from jarvis.integrations.google import (
    NOT_CONNECTED_MSG,
    RECONNECT_MSG,
    GoogleConnector,
    GoogleNotConnected,
    can_use_youtube,
)
from jarvis.tools.card import one_line

API = "https://www.googleapis.com/youtube/v3"
CHANNELS_URL = f"{API}/channels"
ITEMS_URL = f"{API}/playlistItems"
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
CHANNEL_ID = re.compile(r"[A-Za-z0-9_-]{10,40}")
MAX_VIDEOS = 25
DEFAULT_VIDEOS = 10
TITLE_LIMIT = 150
GRANT_MSG = (
    "JARVIS has no permission to read your YouTube account yet. Open Integrations and press "
    "Grant next to 'YouTube', then ask again."
)


class YouTubeNotGranted(RuntimeError):
    """The Google link exists but youtube.readonly is not granted."""


@dataclass(frozen=True)
class Channel:
    channel_id: str
    title: str
    handle: str
    subscribers: int
    videos: int
    views: int
    uploads_playlist: str


@dataclass(frozen=True)
class OwnVideo:
    video_id: str
    title: str
    published_at: str


def _num(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return n if n >= 0 else 0


class YouTubeOwn:
    def __init__(self, google: GoogleConnector) -> None:
        self._g = google

    async def status(self, uid: str) -> dict[str, Any]:
        st = await self._g.status(uid)
        if not st["connected"] or st["needs_reconnect"]:
            return {"connected": False, "reason": "no_google"}
        if not can_use_youtube(st["scopes"]):
            return {"connected": False, "reason": "not_granted"}
        return {"connected": True, "reason": None}

    async def _require(self, uid: str) -> None:
        st = await self._g.status(uid)
        if not st["connected"] or st["needs_reconnect"]:
            raise GoogleNotConnected(RECONNECT_MSG if st["needs_reconnect"] else NOT_CONNECTED_MSG)
        if not can_use_youtube(st["scopes"]):
            raise YouTubeNotGranted(GRANT_MSG)

    async def channel(self, uid: str) -> Channel | None:
        await self._require(uid)
        body = await self._g.request(
            uid,
            "GET",
            CHANNELS_URL,
            params={"part": "snippet,statistics,contentDetails", "mine": "true"},
            send_once=True,
        )
        items = body.get("items") if isinstance(body, dict) else None
        first = (
            items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else None
        )
        return None if first is None else _channel(first)

    async def videos(self, uid: str, limit: int = DEFAULT_VIDEOS) -> tuple[OwnVideo, ...]:
        ch = await self.channel(uid)
        if ch is None or not ch.uploads_playlist:
            return ()
        n = max(1, min(limit, MAX_VIDEOS))
        body = await self._g.request(
            uid,
            "GET",
            ITEMS_URL,
            params={"part": "snippet", "playlistId": ch.uploads_playlist, "maxResults": n},
            send_once=True,
        )
        raw = body.get("items") if isinstance(body, dict) else None
        rows = [r for r in raw if isinstance(r, dict)] if isinstance(raw, list) else []
        return tuple(v for v in (_video(r) for r in rows) if v is not None)[:n]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _channel(item: dict[str, Any]) -> Channel:
    snippet, stats = _dict(item.get("snippet")), _dict(item.get("statistics"))
    related = _dict(_dict(item.get("contentDetails")).get("relatedPlaylists"))
    uploads, cid = related.get("uploads"), item.get("id")
    return Channel(
        cid if isinstance(cid, str) and CHANNEL_ID.fullmatch(cid) else "",
        one_line(snippet.get("title"), TITLE_LIMIT),
        one_line(snippet.get("customUrl"), 60),
        _num(stats.get("subscriberCount")),
        _num(stats.get("videoCount")),
        _num(stats.get("viewCount")),
        uploads if isinstance(uploads, str) and CHANNEL_ID.fullmatch(uploads) else "",
    )


def _video(item: dict[str, Any]) -> OwnVideo | None:
    snippet = item.get("snippet")
    if not isinstance(snippet, dict):
        return None
    rid = snippet.get("resourceId")
    vid = rid.get("videoId") if isinstance(rid, dict) else None
    if not isinstance(vid, str) or not VIDEO_ID.fullmatch(vid):
        return None
    return OwnVideo(
        vid, one_line(snippet.get("title"), TITLE_LIMIT), one_line(snippet.get("publishedAt"), 40)
    )


__all__ = ["Channel", "OwnVideo", "YouTubeNotGranted", "YouTubeOwn"]
