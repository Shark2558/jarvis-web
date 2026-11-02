# src/jarvis/places/google_maps.py
"""Places API (New) Text Search and Routes API computeRoutes over the server key (slice 12 D3;
Layer 6). Shapes verified against the official docs on 2026-11-03:

    POST https://places.googleapis.com/v1/places:searchText
        X-Goog-FieldMask (required, no spaces); body {textQuery, pageSize 1–20, languageCode,
        regionCode (CLDR)}; answer {places: [{id, displayName {text, languageCode},
        formattedAddress, location {latitude, longitude}, googleMapsUri, businessStatus}]}
        (developers.google.com/maps/documentation/places/web-service/text-search). The mask asks
        for Text Search **Pro** fields only — no ratings, hours or phone numbers (Enterprise SKU).
    POST https://routes.googleapis.com/directions/v2:computeRoutes
        X-Goog-FieldMask routes.duration,routes.distanceMeters; body {origin, destination
        (Waypoint: {address} — "Routes API internally geocodes the string"), travelMode DRIVE |
        TWO_WHEELER | WALK, routingPreference TRAFFIC_AWARE ("only when the travelMode is DRIVE
        or TWO_WHEELER, otherwise the request fails"), departureTime RFC 3339 (past only for
        TRANSIT), regionCode, units}; answer {routes: [{distanceMeters int, duration "165s"}]}
        — an empty or missing array means no route (…/routes/reference/rest/v2/TopLevel/
        computeRoutes, …/routes/specify_location).

Everything in an answer is type-checked: a place without a valid id is dropped, every other bad
field is dropped on its own; a route that doesn't read back is "unreadable". Nothing is kept.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from jarvis.integrations.google_key import GoogleKeyClient, KeyAPIError
from jarvis.tools.card import one_line

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
PLACES_FIELD_MASK = ",".join(
    f"places.{f}"
    for f in (
        "id",
        "displayName",
        "formattedAddress",
        "location",
        "googleMapsUri",
        "businessStatus",
    )
)
ROUTES_FIELD_MASK = "routes.duration,routes.distanceMeters"
REGION = "in"
LANGUAGE = "en"
PAGE_SIZE = 5
TEXT_LIMIT = 300
PLACE_ID = re.compile(r"[A-Za-z0-9_-]{1,256}")
_DURATION = re.compile(r"(\d{1,9})(?:\.\d{1,9})?s")
Mode = Literal["drive", "two_wheeler", "walk"]
TRAVEL: dict[str, tuple[str, str | None]] = {  # our mode → (travelMode, routingPreference)
    "drive": ("DRIVE", "TRAFFIC_AWARE"),
    "two_wheeler": ("TWO_WHEELER", "TRAFFIC_AWARE"),
    "walk": ("WALK", None),
}
CLOSED = {
    "CLOSED_TEMPORARILY": "temporarily closed",
    "CLOSED_PERMANENTLY": "permanently closed",
}
UNREADABLE = "Google Maps returned an unreadable response."


@dataclass(frozen=True)
class Place:
    id: str
    name: str
    address: str
    maps_uri: object  # as Google sent it; the card checks it (`reply_cards.google_maps_url`)
    status: str | None = None


@dataclass(frozen=True)
class Route:
    seconds: int
    meters: int


def _text(v: object) -> str:
    return one_line(v, TEXT_LIMIT) if isinstance(v, str) else ""


def _place(item: object) -> Place | None:
    if not isinstance(item, dict):
        return None
    pid = item.get("id")
    if not isinstance(pid, str) or not PLACE_ID.fullmatch(pid):
        return None
    name = item.get("displayName")
    status = item.get("businessStatus")
    return Place(
        id=pid,
        name=_text(name.get("text")) if isinstance(name, dict) else "",
        address=_text(item.get("formattedAddress")),
        maps_uri=item.get("googleMapsUri"),
        status=CLOSED.get(status) if isinstance(status, str) else None,
    )


def _count(v: object) -> int | None:
    if isinstance(v, float) and math.isfinite(v) and v.is_integer():
        v = int(v)
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def _route(item: object) -> Route:
    if not isinstance(item, dict):
        raise KeyAPIError(UNREADABLE)
    meters = _count(item.get("distanceMeters", 0))
    raw = item.get("duration")
    m = _DURATION.fullmatch(raw) if isinstance(raw, str) else None
    if meters is None or m is None:
        raise KeyAPIError(UNREADABLE)
    return Route(seconds=int(m.group(1)), meters=meters)


async def search_text(client: GoogleKeyClient, query: str) -> list[Place]:
    body = {
        "textQuery": query,
        "pageSize": PAGE_SIZE,
        "languageCode": LANGUAGE,
        "regionCode": REGION,
    }
    data = await client.post(PLACES_URL, body, field_mask=PLACES_FIELD_MASK)
    places = data.get("places", [])
    if not isinstance(places, list):
        raise KeyAPIError(UNREADABLE)
    return [p for p in (_place(x) for x in places[: PAGE_SIZE * 2]) if p is not None][:PAGE_SIZE]


async def compute_route(
    client: GoogleKeyClient, origin: str, destination: str, mode: Mode, depart: datetime | None
) -> Route | None:
    travel, preference = TRAVEL[mode]
    body: dict[str, Any] = {
        "origin": {"address": origin},
        "destination": {"address": destination},
        "travelMode": travel,
        "languageCode": LANGUAGE,
        "regionCode": REGION,
        "units": "METRIC",
    }
    if preference is not None:
        body["routingPreference"] = preference
    if depart is not None:
        body["departureTime"] = depart.strftime("%Y-%m-%dT%H:%M:%SZ")
    data = await client.post(ROUTES_URL, body, field_mask=ROUTES_FIELD_MASK)
    routes = data.get("routes", [])
    if not isinstance(routes, list):
        raise KeyAPIError(UNREADABLE)
    return _route(routes[0]) if routes else None


__all__ = [
    "PLACES_FIELD_MASK",
    "PLACES_URL",
    "ROUTES_FIELD_MASK",
    "ROUTES_URL",
    "TRAVEL",
    "Mode",
    "Place",
    "Route",
    "compute_route",
    "search_text",
]
