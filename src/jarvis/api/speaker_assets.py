# src/jarvis/api/speaker_assets.py
"""R5.2 row 84 (docs/plans/r5-2-voice.md 3.5, D6): the speaker check's model file.

    GET /static/vendor/speaker/{release}/{name}

The release folder `static/vendor/speaker/<release>/` (`spk-1`) carries a `MANIFEST.json`
{"files": {name: {sha256, type, ...}}, "slot": {...}}; a file is served only when the manifest
lists it with a matching SHA-256 and a data media type (never JavaScript), with a year's immutable
cache (the release is in the URL). Until the model is pinned the list is empty and every request
is a 404: the console's speaker check then reports "no model" and barge-in works as before. The
check is R7's vision check, read at call time (`console._VisionFiles`, as `tryon_assets` uses it).
No sign-in: the file is the same for everyone and holds nothing of the owner's; his voice print
never leaves his browser, so nothing here receives one.

The speaker check never approves anything (plan D6, slice 9 D11): this module serves a model file
and reads no request header (`tests/test_r52_v5_never_approves.py`).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from jarvis.api.console import _JS, _VENDOR, _VISION_NAME, _VISION_RELEASE, _immutable, _VisionFiles

SPEAKER = _VENDOR / "speaker"
RELEASE = "spk-1"
router = APIRouter()

speaker_files = _VisionFiles(lambda: SPEAKER)


@router.get("/static/vendor/speaker/{release}/{name}", include_in_schema=False)
async def speaker_model(release: str, name: str) -> FileResponse:
    if not (_VISION_RELEASE.fullmatch(release) and _VISION_NAME.fullmatch(name)):
        raise HTTPException(404, "not found")
    kind = speaker_files(release).get(name)
    if kind is None or kind == _JS:  # JavaScript never comes from here
        raise HTTPException(404, "not found")
    return _immutable(SPEAKER / release / name, kind)


__all__ = ["RELEASE", "SPEAKER", "router", "speaker_files"]
