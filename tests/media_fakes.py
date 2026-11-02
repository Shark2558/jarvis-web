# tests/media_fakes.py — a scriptable fake of the Google APIs JARVIS calls with its server-side
# key (slice 12 D2–D4): Places Text Search (New), Routes computeRoutes, YouTube Data v3 search /
# videos / playlists / playlistItems / channels. Shapes as the official docs give them (verified
# 2026-11-03, see jarvis.integrations.google_key). A plain module (not conftest) so test files
# can import it.
from __future__ import annotations

import json
from typing import Any

import httpx

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
YT = "https://www.googleapis.com/youtube/v3"
KEY = "AIza-test-key-not-real"


def place(n: int, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": f"ChIJplace{n:04d}abcdEFGH",
        "displayName": {"text": f"Cafe {n}", "languageCode": "en"},
        "formattedAddress": f"{n} MG Road, Thiruvananthapuram, Kerala 695001, India",
        "location": {"latitude": 8.5 + n / 1000, "longitude": 76.9 + n / 1000},
        "googleMapsUri": f"https://maps.google.com/?cid={1000 + n}",
        "businessStatus": "OPERATIONAL",
    }
    base.update(over)
    return base


def video_id(n: int) -> str:
    return f"vid{n:08d}"[:11].ljust(11, "x")


def search_item(n: int, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "kind": "youtube#searchResult",
        "id": {"kind": "youtube#video", "videoId": video_id(n)},
        "snippet": {
            "title": f"Song {n}",
            "channelTitle": f"Channel {n}",
            "description": "desc",
            "liveBroadcastContent": "none",
        },
    }
    base.update(over)
    return base


def video(
    n: int, *, duration: str = "PT3M5S", embeddable: bool = True, **over: Any
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "kind": "youtube#video",
        "id": video_id(n),
        "snippet": {
            "title": f"Song {n}",
            "channelTitle": f"Channel {n}",
            "categoryId": "10",
            "liveBroadcastContent": "none",
        },
        "contentDetails": {"duration": duration},
        "status": {
            "embeddable": embeddable,
            "privacyStatus": "public",
            "uploadStatus": "processed",
        },
    }
    base.update(over)
    return base


class FakeGoogleKeyAPIs:
    """Records every request; answers from the lists below. `status` makes every call fail with
    that HTTP status (and `body`, Google's error envelope by default)."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.places: list[dict[str, Any]] = [place(i) for i in range(1, 6)]
        self.routes: list[dict[str, Any]] = [{"distanceMeters": 12_345, "duration": "1520s"}]
        self.search: list[dict[str, Any]] = [search_item(i) for i in range(1, 6)]
        self.videos: dict[str, dict[str, Any]] = {video_id(i): video(i) for i in range(1, 30)}
        self.playlists: list[dict[str, Any]] = [
            {
                "id": "PLabc123_-XYZ",
                "snippet": {"title": "Road trip", "channelTitle": "Me"},
                "contentDetails": {"itemCount": 12},
            },
        ]
        self.playlist_items: list[dict[str, Any]] = [
            {
                "snippet": {
                    "title": f"Song {i}",
                    "videoOwnerChannelTitle": f"Channel {i}",
                    "resourceId": {"kind": "youtube#video", "videoId": video_id(i)},
                },
                "contentDetails": {"videoId": video_id(i)},
            }
            for i in range(10, 14)
        ]
        self.likes_id = "LLabcdef_123"
        self.next_page: str | None = None
        self.status: int | None = None
        self.body: Any = {
            "error": {
                "code": 403,
                "message": "vendor words: quota",
                "errors": [{"reason": "quotaExceeded", "message": "vendor words"}],
            }
        }
        self.raw: bytes | None = None

    # ---- inspection ---------------------------------------------------------------------------

    def sent(self, prefix: str) -> list[httpx.Request]:
        return [r for r in self.requests if str(r.url).startswith(prefix)]

    @staticmethod
    def body_of(r: httpx.Request) -> dict[str, Any]:
        return json.loads(r.content or b"{}")

    # ---- transport ----------------------------------------------------------------------------

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status is not None:
            return httpx.Response(self.status, json=self.body)
        if self.raw is not None:
            return httpx.Response(200, content=self.raw)
        url = f"{request.url.scheme}://{request.url.host}{request.url.path}"
        if url == PLACES_URL:
            return httpx.Response(200, json={"places": self.places} if self.places else {})
        if url == ROUTES_URL:
            return httpx.Response(200, json={"routes": self.routes} if self.routes else {})
        q = request.url.params
        if url == f"{YT}/search":
            out: dict[str, Any] = {"items": self.search[: int(q.get("maxResults", 5))]}
            if self.next_page:
                out["nextPageToken"] = self.next_page
            return httpx.Response(200, json=out)
        if url == f"{YT}/videos":
            ids = q.get("id", "").split(",")
            return httpx.Response(
                200, json={"items": [self.videos[i] for i in ids if i in self.videos]}
            )
        if url == f"{YT}/playlists":
            return httpx.Response(200, json={"items": self.playlists})
        if url == f"{YT}/channels":
            return httpx.Response(
                200,
                json={
                    "items": [{"contentDetails": {"relatedPlaylists": {"likes": self.likes_id}}}]
                },
            )
        if url == f"{YT}/playlistItems":
            out = {"items": self.playlist_items}
            if self.next_page:
                out["nextPageToken"] = self.next_page
            return httpx.Response(200, json=out)
        return httpx.Response(404, json={"error": {"code": 404, "message": "unknown"}})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self.handler), follow_redirects=False
        )
