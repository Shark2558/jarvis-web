# src/jarvis/coach/sources.py
"""R8 I0 seam S24 (docs/plans/r8-vision.md 4.5a, the owner's D3): where a camera's pictures are
looked at, which is where its use cases run. Kit-safe: standard library only.

- `browser`: a laptop or desktop browser (the desk webcam): the console's engine, in the page.
- `phone`: the phone (the workout tripod, the table): the same engine, in Chrome or the R7 app.
- `home`: a home IP camera (RTSP/ONVIF, the owner's Imou Ranger S2): the home vision plugin on the
  home laptop reads its sub-stream and runs pose and the home use cases there; only views and
  tallies leave the laptop.

The values are the Result's `device` (`jarvis.vision.results.Result.device`), so a Result says
which kind of camera made it.
"""

from __future__ import annotations

from typing import Literal, get_args

SourceKind = Literal["browser", "phone", "home"]
SOURCES: tuple[SourceKind, ...] = get_args(SourceKind)
DEVICE_SOURCES: frozenset[str] = frozenset({"browser", "phone"})  # the console's engine
HOME_SOURCE: SourceKind = "home"


def runs_in_console(source: str) -> bool:
    """True when the console's engine looks (browser, phone); False for the home laptop."""
    return source in DEVICE_SOURCES


__all__ = ["DEVICE_SOURCES", "HOME_SOURCE", "SOURCES", "SourceKind", "runs_in_console"]
