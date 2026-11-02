# src/jarvis/media/youtube.py
"""YouTube Data API v3 (slice 12 D4; Layer 6). Shapes verified against the official docs on
2026-11-03 (developers.google.com/youtube/v3/docs/…):

    GET /youtube/v3/search         part=snippet, q, type=video, maxResults 0–50, videoCategoryId
                                   (needs type=video; 10 = Music), videoEmbeddable=true (needs
                                   type=video), safeSearch, regionCode → items[].id.videoId,
                                   snippet.title / channelTitle / liveBroadcastContent. Its own
                                   bucket: 100 calls a day, 1 each.
    GET /youtube/v3/videos         part=snippet,contentDetails,status, id=a,b,… → items[].id,
                                   snippet.title / channelTitle, contentDetails.duration (ISO 8601,
                                   "PT15M33S"), status.embeddable. 1 unit.
    GET /youtube/v3/playlists      part=snippet,contentDetails, mine=true (the owner's OAuth) →
                                   items[].id, snippet.title, contentDetails.itemCount. 1 unit.
    GET /youtube/v3/channels       part=contentDetails, mine=true →
                                   contentDetails.relatedPlaylists.likes. 1 unit.
    GET /youtube/v3/playlistItems  part=snippet,contentDetails, playlistId, maxResults 0–50,
                                   pageToken → items[].snippet.title / videoOwnerChannelTitle /
                                   resourceId.videoId, nextPageToken. 1 unit.

"All API requests, including invalid requests, incur a quota cost of at least one point" and
"daily quotas reset at midnight Pacific Time" (…/determine_quota_cost). Watch history has no API.
Every field is type-checked; a video id must be exactly 11 of [A-Za-z0-9_-].
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from jarvis.tools.card import one_line

API = "https://www.googleapis.com/youtube/v3"
SEARCH_URL = f"{API}/search"
VIDEOS_URL = f"{API}/videos"
PLAYLISTS_URL = f"{API}/playlists"
CHANNELS_URL = f"{API}/channels"
ITEMS_URL = f"{API}/playlistItems"
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
PLAYLIST_ID = re.compile(r"[A-Za-z0-9_-]{2,64}")
PAGE_TOKEN = re.compile(r"[A-Za-z0-9_-]{1,128}")
TEXT_LIMIT = 300
_ISO = re.compile(r"P(?:(\d{1,4})D)?(?:T(?:(\d{1,4})H)?(?:(\d{1,4})M)?(?:(\d{1,4})S)?)?")
GONE_TITLES = frozenset({"Deleted video", "Private video"})  # what playlists show for them


@dataclass(frozen=True)
class Video:
    id: str
    title: str
    channel: str = ""
    duration: str = ""
    embeddable: bool = True
    live: bool = False


@dataclass(frozen=True)
class Playlist:
    id: str
    title: str
    count: int | None = None


def _text(v: object) -> str:
    return one_line(v, TEXT_LIMIT) if isinstance(v, str) else ""


def _obj(v: object) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def iso_duration(raw: object) -> str:
    """ "PT3M5S" → "3:05", "PT1H2M3S" → "1:02:03"; "" when unknown or zero (a live stream)."""
    m = _ISO.fullmatch(raw) if isinstance(raw, str) else None
    if m is None:
        return ""
    d, h, mi, s = (int(x or 0) for x in m.groups())
    total = ((d * 24 + h) * 60 + mi) * 60 + s
    if total <= 0:
        return ""
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def video_id_of(raw: object) -> str | None:
    return raw if isinstance(raw, str) and VIDEO_ID.fullmatch(raw) else None


def search_hits(data: dict[str, Any]) -> list[Video]:
    """search.list items that are videos with a valid id, from their snippet."""
    out: list[Video] = []
    items = data.get("items", [])
    for item in items if isinstance(items, list) else []:
        it = _obj(item)
        ident = _obj(it.get("id"))
        vid = video_id_of(ident.get("videoId"))
        if vid is None or ident.get("kind", "youtube#video") != "youtube#video":
            continue
        sn = _obj(it.get("snippet"))
        live = sn.get("liveBroadcastContent") in ("live", "upcoming")
        out.append(Video(vid, _text(sn.get("title")), _text(sn.get("channelTitle")), live=live))
    return out


def details(data: dict[str, Any]) -> dict[str, Video]:
    """videos.list items by id."""
    out: dict[str, Video] = {}
    items = data.get("items", [])
    for item in items if isinstance(items, list) else []:
        it = _obj(item)
        vid = video_id_of(it.get("id"))
        if vid is None:
            continue
        sn, cd, st = _obj(it.get("snippet")), _obj(it.get("contentDetails")), _obj(it.get("status"))
        out[vid] = Video(
            vid,
            _text(sn.get("title")),
            _text(sn.get("channelTitle")),
            iso_duration(cd.get("duration")),
            embeddable=st.get("embeddable") is not False,
            live=sn.get("liveBroadcastContent") in ("live", "upcoming"),
        )
    return out


def playlists(data: dict[str, Any]) -> list[Playlist]:
    out: list[Playlist] = []
    items = data.get("items", [])
    for item in items if isinstance(items, list) else []:
        it = _obj(item)
        pid = it.get("id")
        if not isinstance(pid, str) or not PLAYLIST_ID.fullmatch(pid):
            continue
        count = _obj(it.get("contentDetails")).get("itemCount")
        ok = isinstance(count, int) and not isinstance(count, bool) and count >= 0
        out.append(
            Playlist(pid, _text(_obj(it.get("snippet")).get("title")), count if ok else None)
        )
    return out


def likes_playlist(data: dict[str, Any]) -> str | None:
    items = data.get("items", [])
    first = _obj(items[0]) if isinstance(items, list) and items else {}
    likes = _obj(_obj(first.get("contentDetails")).get("relatedPlaylists")).get("likes")
    return likes if isinstance(likes, str) and PLAYLIST_ID.fullmatch(likes) else None


def playlist_videos(data: dict[str, Any]) -> list[Video]:
    out: list[Video] = []
    items = data.get("items", [])
    for item in items if isinstance(items, list) else []:
        it = _obj(item)
        sn = _obj(it.get("snippet"))
        vid = video_id_of(_obj(sn.get("resourceId")).get("videoId")) or video_id_of(
            _obj(it.get("contentDetails")).get("videoId")
        )
        title = _text(sn.get("title"))
        if vid is None or title in GONE_TITLES:
            continue
        out.append(Video(vid, title, _text(sn.get("videoOwnerChannelTitle"))))
    return out


def next_page(data: dict[str, Any]) -> str | None:
    tok = data.get("nextPageToken")
    return tok if isinstance(tok, str) and PAGE_TOKEN.fullmatch(tok) else None


__all__ = [
    "CHANNELS_URL",
    "ITEMS_URL",
    "PAGE_TOKEN",
    "PLAYLISTS_URL",
    "PLAYLIST_ID",
    "SEARCH_URL",
    "VIDEOS_URL",
    "VIDEO_ID",
    "Playlist",
    "Video",
    "details",
    "iso_duration",
    "likes_playlist",
    "next_page",
    "playlist_videos",
    "playlists",
    "search_hits",
    "video_id_of",
]
