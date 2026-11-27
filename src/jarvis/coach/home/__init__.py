# src/jarvis/coach/home/__init__.py
"""R8 I0 seam S24 (docs/plans/r8-vision.md v8.0.3 section 4.5a, the owner's D3): the home camera's
use cases, run on the home laptop by the home vision plugin (`jarvis.homebridge.homevision`).

Kit-safe: the standard library and Pydantic only (the bridge's image installs nothing of the
cloud's). The browser's use-case contract (console-vision.js `JarvisVision.use`), in Python:

    class HomeUseCase(Protocol):
        id: str                      # one of jarvis.coach.usecases.USE_CASES with source "home"
        tasks: tuple[str, ...]       # what the runtime must run on each frame ("pose", "objects")
        def on_result(self, result: Mapping, state: S | None) -> S       # one body's Result
        def summary(self, state: S | None) -> Summary                    # {view, tally}

The runtime (builder J, `jarvis.coach.home.runtime`) gives each use case one body at a time, as
the console's driver does (`track`, `who`), keeps a state per body, and sends only `Summary`s up
in `CoachReport`s (`jarvis.home.ports`). The rules themselves are builders C's and D's:
`posture.py`, `activity.py` (C), `seated.py`, `bp_posture.py` (D). `REGISTRY` maps each home use
case's id to its factory; I0 leaves it empty, so the runtime starts none.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol, TypedDict


class Summary(TypedDict):
    view: list[dict[str, Any]]  # the fixed widget kinds (jarvis.coach.usecases.VIEW_KINDS)
    tally: dict[str, Any] | None  # the use case's Tally model's fields, or None


class HomeUseCase(Protocol):
    id: str
    tasks: tuple[str, ...]

    def on_result(self, result: Mapping[str, Any], state: Any) -> Any: ...

    def summary(self, state: Any) -> Summary: ...


HOME_USE_CASES: tuple[str, ...] = ("posture", "activity", "seated", "bp-posture")
REGISTRY: dict[str, Callable[[], HomeUseCase]] = {}

__all__ = ["HOME_USE_CASES", "REGISTRY", "HomeUseCase", "Summary"]
