# src/jarvis/api/tryon_assets.py
"""R13.1 D3 (docs/plans/r13-1-try-on.md; I0 seam 6): the 3D figure's files.

    GET /static/vendor/mannequin/{release}/{name}

The release folder `static/vendor/mannequin/<release>/` (Part B's `m1`) carries a
`MANIFEST.json` {"files": {name: {sha256, type, ...}}}; a file is served only when the manifest
lists it with a matching SHA-256 and a media type from `console.VISION_TYPES` other than
JavaScript (the figure's files are data: `application/octet-stream` GLBs and JSON), with a year's
immutable cache (the release is in the URL). A file that fails its sum is a 404, and the engine
falls back to the checklist (D8). The check is R7's vision check, read at call time
(`console._VisionFiles`). No sign-in: the files are the same for everyone and hold nothing of his.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from jarvis.api.console import _JS, _VENDOR, _VISION_NAME, _VISION_RELEASE, _immutable, _VisionFiles

MANNEQUIN = _VENDOR / "mannequin"
RELEASE = "m1"
router = APIRouter()


mannequin_files = _VisionFiles(lambda: MANNEQUIN)


@router.get("/static/vendor/mannequin/{release}/{name}", include_in_schema=False)
async def mannequin(release: str, name: str) -> FileResponse:
    if not (_VISION_RELEASE.fullmatch(release) and _VISION_NAME.fullmatch(name)):
        raise HTTPException(404, "not found")
    kind = mannequin_files(release).get(name)
    if kind is None or kind == _JS:  # JavaScript never comes from here
        raise HTTPException(404, "not found")
    return _immutable(MANNEQUIN / release / name, kind)


__all__ = ["MANNEQUIN", "RELEASE", "mannequin_files", "router"]
