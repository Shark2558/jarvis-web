# src/jarvis/api/camera_spots.py
"""R8 rows 217, 184 (docs/plans/r8-vision.md 4.5; I0 seam S12 skeleton, builder B from I0 on):

    GET  /v1/camera/spots      his cameras, rooms and switches (`jarvis.camera.spots.Spots`)
    PUT  /v1/camera/spots      the whole set, `rev` checked (a stale one is refused)
    POST /v1/camera/health     {camera, fps, ms, last_seen} from a live device, every 5 minutes

I0: each answers 501 `not_built` in plain words; B builds them over `jarvis.coach.ports`'
`CameraSpots` and `CameraHealth`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from jarvis.api.auth import require_auth

NOT_BUILT = {"error": "not_built", "detail": "Camera setup isn't built yet."}
router = APIRouter(prefix="/v1/camera", dependencies=[Depends(require_auth)])


def _not_built() -> JSONResponse:
    return JSONResponse(status_code=501, content=NOT_BUILT, headers={"Cache-Control": "no-store"})


@router.get("/spots", response_model=None)
async def camera_spots() -> JSONResponse:
    return _not_built()


@router.put("/spots", response_model=None)
async def camera_spots_put() -> JSONResponse:
    return _not_built()


@router.post("/health", response_model=None)
async def camera_health() -> JSONResponse:
    return _not_built()


__all__ = ["router"]
