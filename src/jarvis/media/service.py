# src/jarvis/media/service.py
"""Wiring for Maps + YouTube (slice 12 D2–D4): one `GoogleKeyClient` and one allowance ledger
(`jarvis.quota`) shared by both, the owner's Home / Work store, and — for the owner's own
playlists — the Google OAuth link (`GoogleConnector`). No key (or no Docs) → None: none of these
tools is registered, /v1/quota says "not configured". Also the Vitals data (`quota_view`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from jarvis.config import Settings
from jarvis.integrations.google import GoogleConnector
from jarvis.integrations.google_key import GoogleKeyClient, build_google_key_client
from jarvis.places.service import MapsService
from jarvis.places.store import MapsPlaces
from jarvis.quota.ledger import QuotaLedger
from jarvis.storage.docs import Docs


@dataclass
class YouTubeService:
    client: GoogleKeyClient
    ledger: QuotaLedger
    google: GoogleConnector | None = None  # the owner's link: playlists need youtube.readonly


@dataclass
class MediaServices:
    client: GoogleKeyClient
    ledger: QuotaLedger
    maps: MapsService
    youtube: YouTubeService
    places: MapsPlaces = field(init=False)

    def __post_init__(self) -> None:
        self.places = self.maps.places

    async def aclose(self) -> None:
        await self.client.aclose()


def build_media(
    s: Settings,
    docs: Docs,
    *,
    google: GoogleConnector | None = None,
    http: httpx.AsyncClient | None = None,
) -> MediaServices | None:
    client = build_google_key_client(s, http=http)
    if client is None:
        return None
    ledger = QuotaLedger(docs, prefix=s.firestore_prefix)
    places = MapsPlaces(docs, prefix=s.firestore_prefix)
    return MediaServices(
        client=client,
        ledger=ledger,
        maps=MapsService(client, ledger, places),
        youtube=YouTubeService(client, ledger, google=google),
    )


async def quota_view(media: MediaServices | None) -> dict[str, Any]:
    """{configured: false} | {configured: true, <sku>: {period, used, limit, left, reached,
    unreadable}, …}. Counts only: free allowances, never a price."""
    if media is None:
        return {"configured": False}
    return {"configured": True, **(await media.ledger.view())}


__all__ = ["MediaServices", "YouTubeService", "build_media", "quota_view"]
