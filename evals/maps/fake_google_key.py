# evals/maps/fake_google_key.py
"""An in-memory Google for the slice 12 Maps and YouTube evals: Places Text Search (New), Routes
computeRoutes and YouTube Data v3 (search, videos, playlists, channels, playlistItems) over an httpx
MockTransport, in the shapes the official docs give (verified 2026-11-03). Records every request, so
the gates are ASSERTED ON WHAT GOOGLE RECEIVED, not on what the model said. Self-contained (evals
never import from tests/); evals/youtube imports it from here."""

from __future__ import annotations

import json
from typing import Any

import httpx

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
YT = "https://www.googleapis.com/youtube/v3"


def place(n: int, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": f"ChIJeval{n:04d}",
        "displayName": {"text": f"Place {n}", "languageCode": "en"},
        "formattedAddress": f"{n} Statue Road, Thiruvananthapuram, Kerala, India",
        "location": {"latitude": 8.5, "longitude": 76.9},
        "googleMapsUri": f"https://maps.google.com/?cid={7000 + n}",
        "businessStatus": "OPERATIONAL",
    }
    base.update(over)
    return base


def vid(n: int) -> str:
    return f"evalvid{n:04d}"[:11]


def search_item(n: int, **snippet: Any) -> dict[str, Any]:
    return {
        "id": {"kind": "youtube#video", "videoId": vid(n)},
        "snippet": {"title": f"Track {n}", "channelTitle": f"Artist {n}", **snippet},
    }


def video(n: int, **snippet: Any) -> dict[str, Any]:
    return {
        "id": vid(n),
        "snippet": {"title": f"Track {n}", "channelTitle": f"Artist {n}", **snippet},
        "contentDetails": {"duration": "PT4M2S"},
        "status": {"embeddable": True},
    }


class FakeGoogle:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.reset()

    def reset(self) -> None:
        self.requests.clear()
        self.places: list[Any] = [place(i) for i in range(1, 4)]
        self.routes: list[Any] = [{"distanceMeters": 18_400, "duration": "2460s"}]
        self.search: list[Any] = [search_item(i) for i in range(1, 6)]
        self.videos: dict[str, Any] = {vid(i): video(i) for i in range(1, 30)}
        self.playlists: list[Any] = [
            {
                "id": "PLevalRoadTrip",
                "snippet": {"title": "Road trip"},
                "contentDetails": {"itemCount": 3},
            }
        ]
        self.items: list[Any] = [
            {
                "snippet": {
                    "title": f"Track {i}",
                    "videoOwnerChannelTitle": f"Artist {i}",
                    "resourceId": {"kind": "youtube#video", "videoId": vid(i)},
                }
            }
            for i in (7, 8, 9)
        ]
        self.status: int | None = None
        self.error: dict[str, Any] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status is not None:
            return httpx.Response(self.status, json={"error": self.error})
        url = f"{request.url.scheme}://{request.url.host}{request.url.path}"
        q = request.url.params
        if url == PLACES_URL:
            return httpx.Response(200, json={"places": self.places} if self.places else {})
        if url == ROUTES_URL:
            return httpx.Response(200, json={"routes": self.routes} if self.routes else {})
        if url == f"{YT}/search":
            return httpx.Response(200, json={"items": self.search[: int(q.get("maxResults", 5))]})
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
                    "items": [{"contentDetails": {"relatedPlaylists": {"likes": "LLevalLikes"}}}]
                },
            )
        if url == f"{YT}/playlistItems":
            return httpx.Response(200, json={"items": self.items})
        return httpx.Response(404, json={"error": {"code": 404}})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self.handler), follow_redirects=False
        )

    # ---- what Google received -----------------------------------------------------------------

    def sent(self, prefix: str) -> list[httpx.Request]:
        return [r for r in self.requests if str(r.url).startswith(prefix)]

    def bodies(self, url: str) -> list[dict[str, Any]]:
        return [json.loads(r.content or b"{}") for r in self.sent(url)]

    def key_leaks(self, key: str) -> int:
        """Requests that carried the key anywhere but the X-Goog-Api-Key header."""
        return sum(
            key in str(r.url) or key in (r.content or b"").decode("utf-8", "replace")
            for r in self.requests
        )
