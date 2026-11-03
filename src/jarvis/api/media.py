# src/jarvis/api/media.py
"""Maps + YouTube HTTP surface (slice 12 D2/D3; Layer 1). Owner-only: `require_auth` +
`current_user` (a client user id is never used); cookie writes need `X-Requested-With: JARVIS`.

GET /v1/maps/places   {configured, home, work} — the owner's saved places (null when not set);
                      configured false when this server has no Google API key
PUT /v1/maps/places   {home: str | null, work: str | null} (each ≤ 200 characters, one line; an
                      empty string clears it) → same shape; 422 {error: "invalid_place", detail}
                      for text that can't be a place (too long, invisible-only, a phone or account
                      number, an email address); 404 without a key; 409 {error: "switched_off",
                      detail} while the owner's Maps permission row is Never (final review). A
                      save is one audit entry (security review SEC-3: agent "maps", outcome
                      "changed", a hash of the field names only — never the address)
GET /v1/quota         {configured: false} | {configured: true, pricing: india | global,
                      maps_search, maps_route, maps_route_2w, maps_route_walk, youtube_search,
                      youtube_units: {period, used, limit, left, reached, paused_today,
                      unreadable}} — free-allowance counts for Vitals, never a price
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.api.rows import MAPS_TOOL, is_never, switched_off_reply
from jarvis.api.settings_audit import record_change
from jarvis.media.service import MediaServices, quota_view
from jarvis.places.store import PlacesRejected, PlacesUnreadable

router = APIRouter(dependencies=[Depends(require_auth)])
PLACE_FIELDS = ["home", "work"]  # what a save sets (both, always): the audit hashes only these


class PlacesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    home: str | None = None
    work: str | None = None


def _media(request: Request) -> MediaServices | None:
    return getattr(request.app.state, "media", None)


@router.get("/v1/maps/places")
async def get_places(
    media: MediaServices | None = Depends(_media), uid: str = Depends(current_user)
) -> dict[str, Any]:
    if media is None:
        return {"configured": False, "home": None, "work": None}
    try:
        home, work = await media.places.get(uid)
    except PlacesUnreadable as exc:
        raise HTTPException(503, "Your saved Home and Work can't be read right now.") from exc
    return {"configured": True, "home": home, "work": work}


@router.put("/v1/maps/places", response_model=None)
async def put_places(
    body: PlacesIn,
    request: Request,
    media: MediaServices | None = Depends(_media),
    uid: str = Depends(current_user),
) -> dict[str, Any] | JSONResponse:
    if media is None:
        raise HTTPException(404, "Maps is not set up on this server")
    if await is_never(request, uid, MAPS_TOOL):  # the console hides Home / Work; say so plainly
        return switched_off_reply("Maps")
    try:
        home, work = await media.places.put(uid, home=body.home, work=body.work)
    except PlacesRejected as exc:
        return JSONResponse(status_code=422, content={"error": "invalid_place", "detail": str(exc)})
    # SEC-3: the audit chain holds a hash of the field names only, never an address
    await record_change(request, agent="maps", tool="maps_places", args={"fields": PLACE_FIELDS})
    return {"configured": True, "home": home, "work": work}


@router.get("/v1/quota")
async def quota(media: MediaServices | None = Depends(_media)) -> dict[str, Any]:
    return await quota_view(media)


__all__ = ["router"]
