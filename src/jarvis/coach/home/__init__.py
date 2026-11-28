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
case's id to its factory (I0 left it empty; the I1 join fills it with the four rules).
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
ASPECT_MIN, ASPECT_MAX = 0.2, 5.0


def aspect_of(result: Mapping[str, Any], default: float = 1.0) -> float:
    """R8 I1: the Result's frame width / height (`aspect`; the runtime sets it from the frame),
    else `default`. Points are 0..1 of each side: x times this puts both in the frame's height."""
    v = result.get("aspect") if isinstance(result, Mapping) else None
    if isinstance(v, int | float) and not isinstance(v, bool) and ASPECT_MIN <= v <= ASPECT_MAX:
        return float(v)
    return default


def _registry() -> dict[str, Callable[[], HomeUseCase]]:
    """R8 I1: the four home rules' factories (C's posture and activity, D's seated and
    bp-posture), imported here so the kit carries them (all kit-safe: stdlib and Pydantic)."""
    from jarvis.coach.home import activity, bp_posture, posture, seated

    return {
        "posture": posture.create,
        "activity": activity.create,
        "seated": seated.make,
        "bp-posture": bp_posture.make,
    }


REGISTRY: dict[str, Callable[[], HomeUseCase]] = _registry()

__all__ = ["HOME_USE_CASES", "REGISTRY", "HomeUseCase", "Summary", "aspect_of"]
